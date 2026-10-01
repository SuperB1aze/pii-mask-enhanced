"""PDF на входе, обезличенный текст на выходе.

Фикстуры собираются вручную: минимальный валидный PDF - полтора десятка строк,
и это дешевле, чем тянуть в проект генератор ради тестов. Текст в них
латиницей: шрифт фикстуры объявлен WinAnsi, и кириллица в ней вышла бы
кракозябрами - изъян заглушки, а не извлечения. Работа с кириллицей проверяется
всем остальным набором тестов, сюда вынесена только обвязка формата.
"""
import shutil

import pytest

from pii_mask_enhanced.formats.pdf import PdfError, extract_text


def _pdf(path, text: str | None):
    """Валидный PDF: с текстовым слоем или страница-картинка без него."""
    stream = (f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode("latin-1")
              if text is not None else b"")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))
    return path


needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                   reason="нет pdftotext (poppler-utils)")


@needs_poppler
def test_extracts_text_layer(tmp_path):
    src = _pdf(tmp_path / "a.pdf", 'OOO "Romashka", INN 6083778353')
    assert "Romashka" in extract_text(src)


@needs_poppler
def test_scan_without_text_layer_is_an_error(tmp_path):
    """Страница без текста - отказ, а не пустой результат.

    Иначе прогон выглядит успешным: ноль сущностей, пустой файл и никакой
    ошибки, при том что данные остались на страницах картинкой.
    """
    src = _pdf(tmp_path / "scan.pdf", None)
    with pytest.raises(PdfError, match="скан"):
        extract_text(src)


@needs_poppler
def test_broken_file_is_an_error(tmp_path):
    src = tmp_path / "broken.pdf"
    src.write_bytes(b"not a pdf at all")
    with pytest.raises(PdfError):
        extract_text(src)


def test_missing_binary_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr("pii_mask_enhanced.formats.pdf.shutil.which", lambda _: None)
    with pytest.raises(PdfError, match="poppler"):
        extract_text(tmp_path / "any.pdf")


@needs_poppler
def test_cli_masks_pdf_into_markdown(tmp_path):
    """Сквозной путь: .pdf на входе, .masked.md и реестр на выходе."""
    import sys

    from pii_mask_enhanced.interfaces.cli import main

    src = _pdf(tmp_path / "doc.pdf", 'OOO "Romashka", INN 6083778353')
    out = tmp_path / "doc.masked.md"
    argv = ["pii-mask", "mask", str(src), "--types", "INN",
            "-o", str(out), "--mapping", str(tmp_path / "m.json")]
    old, sys.argv = sys.argv, argv
    try:
        with pytest.raises(SystemExit) as exit_info:
            main()          # точка входа завершает процесс, а не возвращает код
        assert exit_info.value.code == 0
    finally:
        sys.argv = old
    body = out.read_text(encoding="utf-8")
    assert "6083778353" not in body
    assert "{{INN_1}}" in body
