"""Документ Word 97-2003: .doc -> временный .docx -> .masked.docx.

Сами конвертеры (LibreOffice, Word) в обычном прогоне подменяются заглушкой,
которая кладет готовый .docx: проверяется обвязка - выбор конвертера, ошибки,
уборка временной копии с незамаскированными ПД. Настоящий Word гоняет
отдельный тест, и только там, где он есть.
"""
import shutil
import sys
from pathlib import Path

import pytest

from pii_mask_enhanced.formats import doc
from pii_mask_enhanced.formats.doc import DocError, as_docx
from pii_mask_enhanced.formats.docx import paragraph_texts
from test_docx import _docx, _para

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504


def _ole(path):
    """Файл с сигнатурой OLE2 - для обвязки этого достаточно, внутрь никто не смотрит."""
    path.write_bytes(OLE_HEADER)
    return path


@pytest.fixture
def fake_converter(monkeypatch, tmp_path):
    """Конвертер, который вместо .doc кладет заранее собранный .docx."""
    template = _docx(tmp_path / "template.docx",
                     [_para(["Директор Соколова Анна Владимировна"])])
    seen = {}

    def convert(src, outdir):
        seen["src"] = src
        dst = outdir / f"{src.stem}.docx"
        shutil.copyfile(template, dst)
        seen["dst"] = dst
        return dst

    monkeypatch.setattr(doc, "_convert", convert)
    return seen


def test_converts_and_removes_temporary_copy(tmp_path, fake_converter):
    src = _ole(tmp_path / "договор с пробелом.doc")
    with as_docx(src) as converted:
        assert paragraph_texts(converted) == ["Директор Соколова Анна Владимировна"]
    # временная копия содержит незамаскированные ПД - после выхода ее нет
    assert not fake_converter["dst"].exists()
    assert not fake_converter["src"].exists()
    # конвертеру отдается копия с простым именем, а не оригинал
    assert fake_converter["src"].name == "source.doc"
    assert src.exists()


def test_temporary_copy_is_removed_on_error(tmp_path, fake_converter):
    src = _ole(tmp_path / "a.doc")
    with pytest.raises(RuntimeError):
        with as_docx(src):
            raise RuntimeError("маскировка упала")
    assert not fake_converter["dst"].exists()


def test_docx_with_doc_extension_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_convert", lambda *a: pytest.fail("конвертировать было нечего"))
    src = _docx(tmp_path / "renamed.doc", [_para(["Текст"])])
    with as_docx(src) as converted:
        assert converted == src


def test_not_a_word_file_is_an_error(tmp_path):
    src = tmp_path / "a.doc"
    src.write_text("просто текст", encoding="utf-8")
    with pytest.raises(DocError, match="не похоже"):
        with as_docx(src):
            pass


def test_converter_without_output_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_convert", lambda src, outdir: outdir / "missing.docx")
    with pytest.raises(DocError, match="не создал"):
        with as_docx(_ole(tmp_path / "a.doc")):
            pass


def test_missing_converter_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_soffice", lambda: None)
    monkeypatch.setattr(doc, "_word_available", lambda: False)
    with pytest.raises(DocError, match="LibreOffice"):
        with as_docx(_ole(tmp_path / "a.doc")):
            pass


def test_configured_soffice_path_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("PII_MASK_SOFFICE", str(tmp_path / "nope" / "soffice"))
    with pytest.raises(DocError, match="PII_MASK_SOFFICE"):
        doc._find_soffice()


def test_configured_soffice_path_wins(monkeypatch, tmp_path):
    exe = tmp_path / "soffice"
    exe.write_bytes(b"")
    monkeypatch.setenv("PII_MASK_SOFFICE", str(exe))
    assert doc._find_soffice() == str(exe)


def _run_cli(argv):
    from pii_mask_enhanced.interfaces.cli import main

    old, sys.argv = sys.argv, ["pii-mask", *argv]
    try:
        with pytest.raises(SystemExit) as exit_info:
            main()
    finally:
        sys.argv = old
    return exit_info.value.code


def test_cli_masks_doc_into_docx(tmp_path, fake_converter):
    """Сквозной путь: .doc на входе, .masked.docx и реестр рядом с исходником."""
    src = _ole(tmp_path / "contract.doc")
    assert _run_cli(["mask", str(src), "--types", "PERSON"]) == 0
    out = tmp_path / "contract.masked.docx"
    text = " ".join(paragraph_texts(out))
    assert "Соколова" not in text
    assert "{{PERSON_1}}" in text
    assert (tmp_path / "contract.mapping.json").exists()


def test_cli_reports_conversion_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doc, "_find_soffice", lambda: None)
    monkeypatch.setattr(doc, "_word_available", lambda: False)
    assert _run_cli(["mask", str(_ole(tmp_path / "a.doc"))]) == 2
    assert "LibreOffice" in capsys.readouterr().err


def test_cli_refuses_to_overwrite_source(tmp_path, fake_converter, capsys):
    src = _ole(tmp_path / "a.doc")
    assert _run_cli(["mask", str(src), "-o", str(src)]) == 2
    assert "один и тот же путь" in capsys.readouterr().err
    assert src.read_bytes() == OLE_HEADER


def _word_ready() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _word_ready(), reason="нет MS Word с pywin32")
def test_real_word_roundtrip(tmp_path, monkeypatch):
    """Настоящий Word: .docx -> .doc (Word же) -> as_docx -> тот же текст."""
    import win32com.client

    monkeypatch.setattr(doc, "_find_soffice", lambda: None)  # именно Word, даже если есть LibreOffice
    paras = ["Займодавец Воронцов Андрей Игоревич", "Заёмщик Белоусова Марина Сергеевна"]
    src_docx = _docx(tmp_path / "src.docx", [_para([p]) for p in paras])
    src_doc = tmp_path / "src.doc"
    word = win32com.client.DispatchEx("Word.Application")
    try:
        d = word.Documents.Open(str(src_docx), ReadOnly=True, Visible=False)
        d.SaveAs2(str(src_doc), FileFormat=0)   # wdFormatDocument97
        d.Close(SaveChanges=0)
    finally:
        word.Quit(SaveChanges=0)
    assert src_doc.read_bytes()[:8] == OLE_HEADER[:8]

    with as_docx(src_doc) as converted:
        assert [t for t in paragraph_texts(converted) if t.strip()] == paras
