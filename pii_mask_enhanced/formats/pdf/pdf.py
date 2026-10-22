"""Извлечение текста из PDF для маскировки"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

BIN = "pdftotext"


class PdfError(Exception):
    """Понятная человеку причина, по которой из PDF не вышло текста."""


def extract_text(src: str | Path, timeout: int = 120) -> str:
    # текст PDF с сохранением расположения колонок
    if shutil.which(BIN) is None:
        raise PdfError(
            f"нет {BIN} - установите poppler-utils, без него PDF читать нечем")

    # -enc UTF-8 прописывается явно: xpdf по умолчанию пишет кодировку Latin-1 и теряет кириллицу
    proc = subprocess.run([BIN, "-enc", "UTF-8", "-layout", str(src), "-"],
                          capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PdfError(f"{BIN} не смог прочитать файл: {detail[-1] if detail else 'без деталей'}")

    # на Windows pdftotext пишет \r\n, а \r в тексте мешает распознаванию ФИО
    text = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if not text.replace("\f", "").strip():
        raise PdfError(
            "В PDF нет текстового слоя. Похоже, что это скан. Маскировка PDF без текста невозможна.")
    return text
