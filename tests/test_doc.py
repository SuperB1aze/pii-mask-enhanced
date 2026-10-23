"""Документ Word 97-2003: .doc -> временный .docx -> .masked.doc.

Сами конвертеры (LibreOffice, Word) в обычном прогоне подменяются заглушкой,
которая кладет готовый .docx: проверяется обвязка - выбор конвертера, ошибки,
уборка временной копии с незамаскированными ПД. Настоящий Word гоняет
отдельный тест, и только там, где он есть.
"""
import shutil
import sys

import pytest

from pii_mask_enhanced.formats.common import legacy
from pii_mask_enhanced.formats.word import DOC, DOCX
from pii_mask_enhanced.formats.common.legacy import ConvertError
from test_docx import _docx, _para

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504


def _ole(path):
    """Файл с сигнатурой OLE2 - для обвязки этого достаточно, внутрь никто не смотрит."""
    path.write_bytes(OLE_HEADER)
    return path


@pytest.fixture
def fake_converter(monkeypatch, tmp_path):
    """Конвертер, который вместо .doc кладет заранее собранный .docx, а вместо
    .docx -> .doc - заголовок OLE2, запомнив текст полученного .docx."""
    template = _docx(tmp_path / "template.docx",
                     [_para(["Директор Соколова Анна Владимировна"])])
    seen = {}

    def convert(src, outdir, fmt="docx", soffice=None):
        if fmt == "doc":
            seen["to_doc"] = DOCX.texts(src)
            return _ole(outdir / f"{src.stem}.doc")
        seen["src"] = src
        dst = outdir / f"{src.stem}.docx"
        shutil.copyfile(template, dst)
        seen["dst"] = dst
        return dst

    monkeypatch.setattr(DOC, "convert", convert)
    return seen


def test_converts_and_removes_temporary_copy(tmp_path, fake_converter):
    src = _ole(tmp_path / "договор с пробелом.doc")
    with DOC.as_new(src) as converted:
        assert DOCX.texts(converted) == ["Директор Соколова Анна Владимировна"]
    # временная копия содержит незамаскированные ПД - после выхода ее нет
    assert not fake_converter["dst"].exists()
    assert not fake_converter["src"].exists()
    # конвертеру отдается копия с простым именем, а не оригинал
    assert fake_converter["src"].name == "source.doc"
    assert src.exists()


def test_temporary_copy_is_removed_on_error(tmp_path, fake_converter):
    src = _ole(tmp_path / "a.doc")
    with pytest.raises(RuntimeError):
        with DOC.as_new(src):
            raise RuntimeError("маскировка упала")
    assert not fake_converter["dst"].exists()


def test_docx_with_doc_extension_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "convert", lambda *a: pytest.fail("конвертировать было нечего"))
    src = _docx(tmp_path / "renamed.doc", [_para(["Текст"])])
    with DOC.as_new(src) as converted:
        assert converted == src


def test_not_a_word_file_is_an_error(tmp_path):
    src = tmp_path / "a.doc"
    src.write_text("просто текст", encoding="utf-8")
    with pytest.raises(ConvertError, match="не похоже"):
        with DOC.as_new(src):
            pass


def test_converter_without_output_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "convert", lambda src, outdir, soffice=None: outdir / "missing.docx")
    with pytest.raises(ConvertError, match="не создал"):
        with DOC.as_new(_ole(tmp_path / "a.doc")):
            pass


def test_missing_converter_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "find_soffice", lambda path=None: None)
    monkeypatch.setattr(legacy, "pywin32_available", lambda: False)
    with pytest.raises(ConvertError, match="LibreOffice"):
        with DOC.as_new(_ole(tmp_path / "a.doc")):
            pass


def test_configured_soffice_path_must_exist(tmp_path):
    with pytest.raises(ConvertError, match="не найден"):
        legacy.find_soffice(tmp_path / "nope" / "soffice")


def test_configured_soffice_path_wins(tmp_path):
    exe = tmp_path / "soffice"
    exe.write_bytes(b"")
    assert legacy.find_soffice(exe) == str(exe)


def test_library_ignores_soffice_environment(monkeypatch, tmp_path):
    """Окружение читает только CLI: библиотека берет путь из параметра."""
    monkeypatch.setenv("PII_MASK_SOFFICE", str(tmp_path / "nope" / "soffice"))
    legacy.find_soffice()


def test_cli_passes_soffice_from_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PII_MASK_SOFFICE", str(tmp_path / "nope" / "soffice"))
    assert _run_cli(["mask", str(_ole(tmp_path / "a.doc"))]) == 2
    assert "не найден" in capsys.readouterr().err


def _run_cli(argv):
    from pii_mask_enhanced.cli.cli import main

    old, sys.argv = sys.argv, ["pii-mask", *argv]
    try:
        with pytest.raises(SystemExit) as exit_info:
            main()
    finally:
        sys.argv = old
    return exit_info.value.code


def test_cli_masks_doc_into_doc(tmp_path, fake_converter):
    """Сквозной путь: .doc на входе, .masked.doc и реестр рядом с исходником."""
    src = _ole(tmp_path / "contract.doc")
    assert _run_cli(["mask", str(src), "--types", "PERSON"]) == 0
    assert (tmp_path / "contract.masked.doc").read_bytes()[:8] == OLE_HEADER[:8]
    text = " ".join(fake_converter["to_doc"])
    assert "Соколова" not in text
    assert "{{PERSON_1}}" in text
    assert (tmp_path / "contract.mapping.json").exists()


def test_cli_masks_doc_into_docx_by_output_name(tmp_path, fake_converter):
    src = _ole(tmp_path / "contract.doc")
    out = tmp_path / "contract.masked.docx"
    assert _run_cli(["mask", str(src), "--types", "PERSON", "-o", str(out)]) == 0
    assert "{{PERSON_1}}" in " ".join(DOCX.texts(out))
    assert "to_doc" not in fake_converter


def test_cli_unmasks_doc_into_doc(tmp_path, fake_converter):
    """masked .doc -> .unmasked.doc; в .doc уходит текст с оригиналами."""
    import json

    masked = _docx(tmp_path / "contract.masked.doc", [_para(["Директор {{PERSON_1}}"])])
    mp = tmp_path / "contract.mapping.json"
    mp.write_text(json.dumps({"version": 1, "labels": {"{{PERSON_1}}": {
        "type": "PERSON", "original": "Соколова Анна", "key": "соколова анна", "n": 1}}},
        ensure_ascii=False), encoding="utf-8")
    assert _run_cli(["unmask", str(masked), "--mapping", str(mp)]) == 0
    assert (tmp_path / "contract.unmasked.doc").read_bytes()[:8] == OLE_HEADER[:8]
    assert fake_converter["to_doc"] == ["Директор Соколова Анна"]


def test_cli_reports_conversion_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(legacy, "find_soffice", lambda path=None: None)
    monkeypatch.setattr(legacy, "pywin32_available", lambda: False)
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
    """Настоящий Word: .docx -> .doc (Word же) -> DOC.as_new -> тот же текст."""
    import win32com.client

    monkeypatch.setattr(legacy, "find_soffice", lambda path=None: None)  # именно Word, даже если есть LibreOffice
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

    with DOC.as_new(src_doc) as converted:
        assert [t for t in DOCX.texts(converted) if t.strip()] == paras


def test_cli_masks_docx_with_doc_extension(tmp_path, fake_converter):
    """.docx, переименованный в .doc, маскируется без конвертации туда и без рекурсии."""
    src = _docx(tmp_path / "renamed.doc", [_para(["Директор Соколова Анна Владимировна"])])
    assert _run_cli(["mask", str(src), "--types", "PERSON"]) == 0
    assert "src" not in fake_converter
    assert "{{PERSON_1}}" in " ".join(fake_converter["to_doc"])
    assert (tmp_path / "renamed.masked.doc").exists()
