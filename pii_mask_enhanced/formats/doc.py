"""Документ Word 97-2003 (.doc): перевод в .docx внешним конвертером"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# составной файл OLE2 - контейнер старого .doc (и зашифрованного .docx)
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)

TIMEOUT = 120
_WD_FORMAT_DOCX = 16                  # wdFormatDocumentDefault
_MSO_FORCE_DISABLE_MACROS = 3         # msoAutomationSecurityForceDisable


class DocError(Exception):
    """Понятная человеку причина, по которой .doc не удалось перевести в .docx."""


def _sniff(path: Path) -> str:
    # формат по сигнатуре: расширение .doc бывает и у настоящего .docx
    try:
        with path.open("rb") as f:
            head = f.read(8)
    except OSError as exc:
        raise DocError(f"не удалось прочитать {path}: {exc.strerror}") from exc
    if head.startswith(_ZIP_MAGIC):
        return "docx"
    if head == _OLE_MAGIC:
        return "doc"
    raise DocError(f"{path.name}: не похоже на документ Word 97-2003 или .docx")


def _find_soffice() -> str | None:
    configured = os.environ.get("PII_MASK_SOFFICE")
    if configured:
        if not Path(configured).is_file():
            raise DocError(f"PII_MASK_SOFFICE указывает на несуществующий файл: {configured}")
        return configured
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    # архив с сайта ставится в каталог с номером версии: /opt/libreoffice25.2
    versioned = sorted(glob.glob("/opt/libreoffice*/program/soffice"), reverse=True)
    return next((p for p in (*_SOFFICE_PATHS, *versioned) if Path(p).is_file()), None)


def _word_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _via_libreoffice(soffice: str, src: Path, outdir: Path) -> Path:
    # Свой профиль на каждый вызов
    profile = (outdir / "lo-profile").as_uri()
    cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
           "--convert-to", "docx", "--outdir", str(outdir), str(src)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise DocError(f"LibreOffice не уложился в {TIMEOUT} с - файл поврежден "
                       "или защищен паролем") from exc
    except OSError as exc:
        raise DocError(f"не удалось запустить LibreOffice ({soffice}): {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DocError("LibreOffice не смог сконвертировать файл: "
                       f"{detail[-1] if detail else 'без деталей'}")
    return outdir / f"{src.stem}.docx"


def _via_word(src: Path, outdir: Path) -> Path:
    import pythoncom
    import pywintypes
    import win32com.client

    dst = outdir / f"{src.stem}.docx"
    pythoncom.CoInitialize()        # без этого COM не работает вне главного потока
    try:
        word = win32com.client.DispatchEx("Word.Application")  # свой экземпляр, не открытый пользователем
        try:
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = _MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
            try:
                doc = word.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                          AddToRecentFiles=False, PasswordDocument="#",
                                          Visible=False, NoEncodingDialog=True)
            except pywintypes.com_error as exc:
                raise DocError("Word не открыл файл - он защищен паролем или поврежден") from exc
            try:
                doc.SaveAs2(str(dst), FileFormat=_WD_FORMAT_DOCX)
            except pywintypes.com_error as exc:
                raise DocError("Word не смог сохранить файл в .docx") from exc
            finally:
                doc.Close(SaveChanges=0)
        finally:
            word.Quit(SaveChanges=0)
    finally:
        pythoncom.CoUninitialize()
    return dst


def _check_docx(path: Path) -> None:
    # конвертер может завершиться успешно и ничего не создать
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise DocError("конвертер не создал .docx")
    with zipfile.ZipFile(path) as z:
        if "word/document.xml" not in z.namelist():
            raise DocError("результат конвертации не похож на документ Word")


def _convert(src: Path, outdir: Path) -> Path:
    soffice = _find_soffice()
    if soffice:
        return _via_libreoffice(soffice, src, outdir)
    if _word_available():
        return _via_word(src, outdir)
    if sys.platform == "win32":
        raise DocError("для .doc нужен LibreOffice или MS Word с pywin32 "
                       "(pip install .[word]); либо пересохраните файл в .docx")
    raise DocError("для .doc нужен LibreOffice (soffice); путь к нему можно задать "
                   "в PII_MASK_SOFFICE, либо пересохраните файл в .docx")


@contextmanager
def as_docx(src: str | Path) -> Iterator[Path]:
    """Путь к .docx-версии файла; промежуточные файлы удаляются при выходе.

    Промежуточный .docx содержит незамаскированные ПД, поэтому живет только во
    временном каталоге и удаляется и при ошибке тоже.
    """
    src = Path(src)
    if _sniff(src) == "docx":
        yield src                   # .docx с чужим расширением - конвертировать нечего
        return

    with tempfile.TemporaryDirectory(prefix="pii-doc-") as tmp:
        tmp_dir = Path(tmp)
        # Конвертируем копию с простым именем
        work = tmp_dir / "source.doc"
        shutil.copyfile(src, work)
        dst = _convert(work.resolve(), tmp_dir.resolve())
        _check_docx(dst)
        yield dst
