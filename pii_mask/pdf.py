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

    proc = subprocess.run([BIN, "-layout", str(src), "-"],
                          capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PdfError(f"{BIN} не смог прочитать файл: {detail[-1] if detail else 'без деталей'}")

    text = proc.stdout.decode("utf-8", "replace")
    if not text.replace("\f", "").strip():
        raise PdfError(
            "В PDF нет текстового слоя. Похоже, что это скан. Маскировка PDF без текста невозможна.")
    return text
