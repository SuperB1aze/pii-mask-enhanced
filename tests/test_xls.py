"""Книга Excel 97-2003: .xls -> временный .xlsx -> .masked.xls.

Конвертеры (LibreOffice, Excel) подменяются заглушкой, которая кладет готовый
.xlsx: проверяется обвязка - выбор конвертера, ошибки, уборка временной копии
с незамаскированными ПД.
"""
import json
import shutil

import pytest

from pii_mask_enhanced.formats.common import legacy
from pii_mask_enhanced.formats.common.legacy import ConvertError
from pii_mask_enhanced.formats.excel import XLS, XLSX
from test_doc import OLE_HEADER, _ole, _run_cli
from test_xlsx import _book


@pytest.fixture
def fake_converter(monkeypatch, tmp_path):
    """Конвертер, который вместо .xls кладет заранее собранный .xlsx, а вместо
    .xlsx -> .xls - заголовок OLE2, запомнив текст полученного .xlsx."""
    (tmp_path / "tpl").mkdir()
    template = _book(tmp_path / "tpl", ["Почта sokolova@example.ru"])
    seen = {}

    def convert(src, outdir, fmt="xlsx", soffice=None):
        if fmt == "xls":
            seen["to_xls"] = XLSX.texts(src)
            return _ole(outdir / f"{src.stem}.xls")
        seen["src"] = src
        dst = outdir / f"{src.stem}.xlsx"
        shutil.copyfile(template, dst)
        seen["dst"] = dst
        return dst

    monkeypatch.setattr(XLS, "convert", convert)
    return seen


def test_converts_and_removes_temporary_copy(tmp_path, fake_converter):
    src = _ole(tmp_path / "book.xls")
    with XLS.as_new(src) as converted:
        assert XLSX.texts(converted) == ["Почта sokolova@example.ru"]
    assert not fake_converter["dst"].exists()
    assert not fake_converter["src"].exists()
    assert fake_converter["src"].name == "source.xls"


def test_xlsx_with_xls_extension_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(XLS, "convert", lambda *a: pytest.fail("конвертировать было нечего"))
    book = _book(tmp_path, ["Итого"])
    src = book.rename(tmp_path / "renamed.xls")
    with XLS.as_new(src) as converted:
        assert converted == src


def test_not_an_excel_file_is_an_error(tmp_path):
    src = tmp_path / "a.xls"
    src.write_bytes(b"not a workbook")
    with pytest.raises(ConvertError, match="Excel"):
        with XLS.as_new(src):
            pass


def test_missing_converter_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "find_soffice", lambda path=None: None)
    monkeypatch.setattr(legacy, "pywin32_available", lambda: False)
    with pytest.raises(ConvertError, match="LibreOffice"):
        with XLS.as_new(_ole(tmp_path / "a.xls")):
            pass


def test_cli_masks_xls_into_xls(tmp_path, fake_converter):
    src = _ole(tmp_path / "list.xls")
    assert _run_cli(["mask", str(src), "--types", "EMAIL", "--no-ner"]) == 0
    assert (tmp_path / "list.masked.xls").read_bytes()[:8] == OLE_HEADER[:8]
    assert fake_converter["to_xls"] == ["Почта user1@example.com"]
    assert (tmp_path / "list.mapping.json").exists()


def test_cli_masks_xls_into_xlsx_by_output_name(tmp_path, fake_converter):
    src = _ole(tmp_path / "list.xls")
    out = tmp_path / "list.masked.xlsx"
    assert _run_cli(["mask", str(src), "--types", "EMAIL", "--no-ner", "-o", str(out)]) == 0
    assert XLSX.texts(out) == ["Почта user1@example.com"]
    assert "to_xls" not in fake_converter


def test_cli_unmasks_xls_into_xls(tmp_path, fake_converter):
    masked = _book(tmp_path, ["Почта user1@example.com"]).rename(tmp_path / "list.masked.xls")
    mp = tmp_path / "list.mapping.json"
    mp.write_text(json.dumps({"version": 1, "labels": {"user1@example.com": {
        "type": "EMAIL", "original": "sokolova@example.ru", "key": "sokolova@example.ru", "n": 1}}},
        ensure_ascii=False), encoding="utf-8")
    assert _run_cli(["unmask", str(masked), "--mapping", str(mp)]) == 0
    assert (tmp_path / "list.unmasked.xls").read_bytes()[:8] == OLE_HEADER[:8]
    assert fake_converter["to_xls"] == ["Почта sokolova@example.ru"]
