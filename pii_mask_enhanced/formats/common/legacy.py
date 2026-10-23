"""Старые форматы Office (.doc, .ppt): перевод в Office Open XML внешним конвертером и обратно"""
from __future__ import annotations

import glob
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

# составной файл OLE2 - контейнер старых форматов (и зашифрованных новых)
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"

_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)

TIMEOUT = 120
MSO_FORCE_DISABLE_MACROS = 3          # msoAutomationSecurityForceDisable


class ConvertError(Exception):
    """Понятная человеку причина, по которой файл не удалось сконвертировать."""


def find_soffice(configured: str | Path | None = None) -> str | None:
    # явно заданный путь обязан существовать; без него - автопоиск
    if configured:
        if not Path(configured).is_file():
            raise ConvertError(f"LibreOffice не найден по указанному пути: {configured}")
        return str(configured)
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    # архив с сайта ставится в каталог с номером версии: /opt/libreoffice25.2
    versioned = sorted(glob.glob("/opt/libreoffice*/program/soffice"), reverse=True)
    return next((p for p in (*_SOFFICE_PATHS, *versioned) if Path(p).is_file()), None)


def pywin32_available() -> bool:
    # через pywin32 доступны Word и PowerPoint
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


@contextmanager
def office_app(prog_id: str, quit: Callable[[object], None]) -> Iterator:
    """Свой экземпляр приложения Office, не открытый пользователем; quit - как его закрыть."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()        # без этого COM не работает вне главного потока
    try:
        app = win32com.client.DispatchEx(prog_id)
        try:
            yield app
        finally:
            quit(app)
    finally:
        pythoncom.CoUninitialize()


@contextmanager
def com_failure(message: str) -> Iterator[None]:
    """Ошибка COM - понятной причиной."""
    import pywintypes

    try:
        yield
    except pywintypes.com_error as exc:
        raise ConvertError(message) from exc


def _via_libreoffice(soffice: str, src: Path, outdir: Path, fmt: str) -> Path:
    # Свой профиль на каждый вызов
    profile = (outdir / "lo-profile").as_uri()
    cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
           "--convert-to", fmt, "--outdir", str(outdir), str(src)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ConvertError(f"LibreOffice не уложился в {TIMEOUT} с - файл поврежден "
                           "или защищен паролем") from exc
    except OSError as exc:
        raise ConvertError(f"не удалось запустить LibreOffice ({soffice}): {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ConvertError("LibreOffice не смог сконвертировать файл: "
                           f"{detail[-1] if detail else 'без деталей'}")
    return outdir / f"{src.stem}.{fmt}"


@dataclass
class LegacyFormat:
    """Старый формат и его пара в Office Open XML."""
    old: str                                            # ".doc"
    new: str                                            # ".docx"
    main_part: str                                      # без этой части результат - не тот формат
    title: str                                          # "документ Word" - для сообщений
    app: str                                            # "MS Word"
    via_office: Callable[[Path, Path, str], Path]       # конвертация самим приложением Office
    locked: Callable[[bytes], bool] | None = None       # файл с паролем: приложение повиснет на нем

    def sniff(self, path: Path) -> str:
        # формат по сигнатуре: старое расширение бывает и у файла нового формата
        try:
            with path.open("rb") as f:
                blob = f.read() if self.locked else f.read(8)
        except OSError as exc:
            raise ConvertError(f"не удалось прочитать {path}: {exc.strerror}") from exc
        if blob.startswith(ZIP_MAGIC):
            return self.new
        if blob[:8] == OLE_MAGIC:
            if self.locked and self.locked(blob):
                raise ConvertError(f"{path.name}: файл защищен паролем - снимите пароль и повторите")
            return self.old
        raise ConvertError(f"{path.name}: не похоже на {self.title} 97-2003 или {self.new}")

    def convert(self, src: Path, outdir: Path, fmt: str | None = None,
                soffice: str | Path | None = None) -> Path:
        # soffice - путь к LibreOffice; без него - автопоиск, затем приложение Office
        fmt = fmt or self.new[1:]
        soffice = find_soffice(soffice)
        if soffice:
            return _via_libreoffice(soffice, src, outdir, fmt)
        if pywin32_available():
            return self.via_office(src, outdir, fmt)
        if sys.platform == "win32":
            raise ConvertError(f"для {self.old} нужен LibreOffice или {self.app} с pywin32 "
                               f"(pip install .[word]); либо пересохраните файл в {self.new}")
        raise ConvertError(f"для {self.old} нужен LibreOffice (soffice): установите его или укажите "
                           f"путь к нему, либо пересохраните файл в {self.new}")

    def _check_new(self, path: Path) -> None:
        # конвертер может завершиться успешно и ничего не создать
        if not path.is_file() or not zipfile.is_zipfile(path):
            raise ConvertError(f"конвертер не создал {self.new}")
        with zipfile.ZipFile(path) as z:
            if self.main_part not in z.namelist():
                raise ConvertError(f"результат конвертации не похож на {self.title}")

    @contextmanager
    def as_new(self, src: str | Path, soffice: str | Path | None = None) -> Iterator[Path]:
        """Путь к версии файла в новом формате; промежуточные файлы удаляются при выходе.

        Промежуточный файл содержит незамаскированные ПД, поэтому живет только во
        временном каталоге и удаляется и при ошибке тоже.
        """
        src = Path(src)
        if self.sniff(src) == self.new:
            yield src                   # новый формат с чужим расширением - конвертировать нечего
            return

        with tempfile.TemporaryDirectory(prefix=f"pii-{self.old[1:]}-") as tmp:
            tmp_dir = Path(tmp)
            # Конвертируем копию с простым именем
            work = tmp_dir / f"source{self.old}"
            shutil.copyfile(src, work)
            dst = self.convert(work.resolve(), tmp_dir.resolve(), soffice=soffice)
            self._check_new(dst)
            yield dst

    def save_as_old(self, src: str | Path, dst: str | Path, soffice: str | Path | None = None) -> None:
        """Сохранить файл нового формата в старом."""
        with tempfile.TemporaryDirectory(prefix=f"pii-{self.old[1:]}-") as tmp:
            tmp_dir = Path(tmp).resolve()
            work = tmp_dir / f"source{self.new}"
            shutil.copyfile(src, work)
            out = self.convert(work, tmp_dir, self.old[1:], soffice=soffice)
            if not out.is_file() or self.sniff(out) != self.old:
                raise ConvertError(f"конвертер не создал {self.old}")
            shutil.copyfile(out, dst)
