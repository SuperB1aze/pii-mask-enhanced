"""Публичный API: маскировка и восстановление файла по его расширению.

Общий для CLI и любого другого кода (например, сайта): формат выбирается здесь,
.doc, .xls и .ppt конвертируются через LibreOffice, PDF маскируется текстом.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

from .audit.base import AuditError, Auditor
from .detection.ner.ner import NatashaNer
from .engine.core import Masker
from .engine.settings import Options, build_masker
from .formats import excel, powerpoint, word
from .formats.common.legacy import ConvertError
from .formats.pdf import PdfError, extract_text

# Формат Office Open XML: маскируется и восстанавливается в файл того же формата
OFFICE = {".xlsx": excel.XLSX, ".docx": word.DOCX, ".pptx": powerpoint.PPTX}
# старый формат: работаем с его версией в новом
LEGACY = {".doc": word.DOC, ".xls": excel.XLS, ".ppt": powerpoint.PPT}
# файл с другим расширением читается как текст UTF-8
TEXT = frozenset({".txt", ".md", ".csv", ".log"})

SUPPORTED_EXTENSIONS = frozenset({*OFFICE, *LEGACY, ".pdf", *TEXT})

# текст документа одной строкой - для выбора набора по профилю
_READERS = {
    ".docx": lambda path: "\n".join(word.DOCX.texts(path)),
    ".pptx": lambda path: "\n".join(powerpoint.PPTX.texts(path)),
}

Report = Callable[[str], None]


class MaskError(Exception):
    """Файл не удалось замаскировать или восстановить; текст - для пользователя."""


def warm_up() -> None:
    """Загрузить модели NER заранее, чтобы первый документ не ждал их загрузки."""
    NatashaNer.shared()


def read_text(src: str | Path) -> str:
    """Текст файла для маскировки: PDF - извлеченный текст, остальное - UTF-8."""
    if Path(src).suffix.lower() == ".pdf":
        # собрать PDF обратно нельзя: замена другой длины ломает верстку строки
        try:
            return extract_text(src)
        except PdfError as exc:
            raise MaskError(str(exc)) from exc
    return Path(src).read_text(encoding="utf-8")


def mask_text(text: str, options: Options | None = None, mapping: dict | None = None, *,
              auditor: Auditor | None = None, report: Report | None = None) -> tuple[str, dict]:
    """Замаскированный текст и реестр замен; существующий mapping продолжается."""
    masker = _masker(options, lambda: text, auditor, report)
    mask = masker.mask_with_audit if auditor else masker.mask
    try:
        return mask(text, mapping)
    except AuditError as exc:       # аудит не завершился целиком - fail-closed
        raise MaskError(str(exc)) from exc
    except RuntimeError as exc:     # например, необязательная зависимость httpx не установлена
        raise MaskError(str(exc)) from exc


def unmask_text(text: str, mapping: dict) -> str:
    return Masker(ner=False).unmask(text, mapping)


def mask_file(src: str | Path, dst: str | Path, options: Options | None = None,
              mapping: dict | None = None, *, soffice: str | Path | None = None,
              auditor: Auditor | None = None, report: Report | None = None) -> dict:
    """Замаскировать файл src в dst и вернуть реестр замен (его сохраняет вызывающий).

    Office пишется в тот же формат, .doc (.xls, .ppt) - в старый или в новый по
    расширению dst, PDF и текст - текстом. report получает пояснения к выбору набора.
    """
    src, dst = Path(src), Path(dst)
    _check_target(src, dst)
    kind = src.suffix.lower()
    if kind in LEGACY:
        return _mask_legacy(src, dst, kind, options, mapping, soffice, auditor, report)
    if kind in OFFICE:
        masker = _masker(options, lambda: _probe(src, kind), auditor, report)
        try:
            return OFFICE[kind].mask(src, dst, masker, mapping)
        except AuditError as exc:
            raise MaskError(str(exc)) from exc
        except RuntimeError as exc:  # например, необязательная зависимость httpx не установлена
            raise MaskError(str(exc)) from exc
        except ValueError as exc:   # в файле есть то, что не удается обезличить
            raise MaskError(str(exc)) from exc
    masked, mapping = mask_text(read_text(src), options, mapping, auditor=auditor, report=report)
    dst.write_text(masked, encoding="utf-8")
    return mapping


def unmask_file(src: str | Path, dst: str | Path, mapping: dict, *,
                soffice: str | Path | None = None) -> None:
    """Вернуть оригиналы в файл src и записать в dst; Office - в файл того же формата."""
    src, dst = Path(src), Path(dst)
    _check_target(src, dst)
    kind = src.suffix.lower()
    try:
        if kind in OFFICE:
            OFFICE[kind].unmask(src, dst, mapping)
        elif kind in LEGACY:
            _unmask_legacy(src, dst, kind, mapping, soffice)
        else:
            dst.write_text(unmask_text(src.read_text(encoding="utf-8"), mapping), encoding="utf-8")
    except (ConvertError, ValueError) as exc:
        raise MaskError(str(exc)) from exc


def _mask_legacy(src: Path, dst: Path, kind: str, options: Options | None, mapping: dict | None,
                 soffice, auditor: Auditor | None, report: Report | None) -> dict:
    # .doc (.xls, .ppt) переводится во временный .docx (.xlsx, .pptx), маскируется в нем и
    # сохраняется обратно в старый формат (или в новый, если так задан dst)
    fmt = LEGACY[kind]
    to_old = dst.suffix.lower() == kind
    try:
        with fmt.as_new(src, soffice) as converted, \
                tempfile.TemporaryDirectory(prefix="pii-legacy-") as tmp:
            if converted.suffix.lower() != fmt.new:
                converted = Path(shutil.copyfile(converted, Path(tmp) / f"source{fmt.new}"))
            new_out = Path(tmp) / f"masked{fmt.new}" if to_old else dst
            mapping = mask_file(converted, new_out, options, mapping,
                                soffice=soffice, auditor=auditor, report=report)
            if to_old:
                fmt.save_as_old(new_out, dst, soffice)
            return mapping
    except ConvertError as exc:
        raise MaskError(str(exc)) from exc


def _unmask_legacy(src: Path, dst: Path, kind: str, mapping: dict, soffice) -> None:
    # .doc (.xls, .ppt) -> временный .docx (.xlsx, .pptx) -> оригиналы -> снова старый формат
    fmt = LEGACY[kind]
    with fmt.as_new(src, soffice) as converted, \
            tempfile.TemporaryDirectory(prefix="pii-legacy-") as tmp:
        restored = Path(tmp) / f"restored{fmt.new}"
        OFFICE[fmt.new].unmask(converted, restored, mapping)
        if dst.suffix.lower() == kind:
            fmt.save_as_old(restored, dst, soffice)
        else:
            shutil.copyfile(restored, dst)


def _masker(options: Options | None, probe: Callable[[], str | None],
            auditor: Auditor | None, report: Report | None) -> Masker:
    try:
        masker, notes = build_masker(options or Options(), probe, auditor)
    except ValueError as exc:       # неизвестный набор или тип
        raise MaskError(str(exc)) from exc
    for note in notes:
        if report:
            report(note)
    return masker


def _probe(path: Path, kind: str) -> str | None:
    # Текст документа для определения профиля; None - прочитать не вышло
    if kind not in _READERS:
        return None
    try:
        return _READERS[kind](path)
    except Exception:                                 # noqa: BLE001
        return None


def _check_target(src: Path, dst: Path) -> None:
    # запись в тот же файл стерла бы исходник до чтения
    if src == dst:
        raise MaskError(f"результат и исходный файл - один и тот же путь ({dst})")
