"""Презентация PowerPoint 97-2003: .ppt -> временный .pptx -> .masked.ppt.

Конвертеры (LibreOffice, PowerPoint) подменяются заглушкой, которая кладет
готовый .pptx: проверяется обвязка - выбор конвертера, ошибки, уборка временной
копии с незамаскированными ПД.
"""
import json
import shutil

import pytest

from pii_mask_enhanced.formats.common import legacy
from pii_mask_enhanced.formats.common.legacy import ConvertError
from pii_mask_enhanced.formats.powerpoint import PPT, PPTX
from test_doc import OLE_HEADER, _ole
from test_pptx import _para, _pptx, _run_cli, _shape, _slide


@pytest.fixture
def fake_converter(monkeypatch, tmp_path):
    """Конвертер, который вместо .ppt кладет заранее собранный .pptx, а вместо
    .pptx -> .ppt - заголовок OLE2, запомнив текст полученного .pptx."""
    template = _pptx(tmp_path / "template.pptx",
                     [_slide(_shape([_para(["Почта sokolova@example.ru"])]))])
    seen = {}

    def convert(src, outdir, fmt="pptx", soffice=None):
        if fmt == "ppt":
            seen["to_ppt"] = PPTX.texts(src)
            return _ole(outdir / f"{src.stem}.ppt")
        seen["src"] = src
        dst = outdir / f"{src.stem}.pptx"
        shutil.copyfile(template, dst)
        seen["dst"] = dst
        return dst

    monkeypatch.setattr(PPT, "convert", convert)
    return seen


def test_converts_and_removes_temporary_copy(tmp_path, fake_converter):
    src = _ole(tmp_path / "deck.ppt")
    with PPT.as_new(src) as converted:
        assert PPTX.texts(converted) == ["Почта sokolova@example.ru"]
    assert not fake_converter["dst"].exists()
    assert not fake_converter["src"].exists()
    assert fake_converter["src"].name == "source.ppt"


def test_pptx_with_ppt_extension_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(PPT, "convert", lambda *a: pytest.fail("конвертировать было нечего"))
    src = _pptx(tmp_path / "renamed.ppt", [_slide(_shape([_para(["Итоги"])]))])
    with PPT.as_new(src) as converted:
        assert converted == src


def test_not_a_powerpoint_file_is_an_error(tmp_path):
    src = tmp_path / "a.ppt"
    src.write_bytes(b"not a presentation")
    with pytest.raises(ConvertError, match="PowerPoint"):
        with PPT.as_new(src):
            pass


CURRENT_USER = b"\x00\x00\xf6\x0f" + b"\x00" * 4 + b"\x14\x00\x00\x00"


@pytest.mark.parametrize("tail", [CURRENT_USER + b"\xdf\xc4\xd1\xf3",
                                  "EncryptedPackage".encode("utf-16-le")])
def test_password_protected_file_is_refused_before_converter(tmp_path, monkeypatch, tail):
    """PowerPoint на файле с паролем ждет ввода вечно - до конвертера такой файл не пускаем."""
    monkeypatch.setattr(PPT, "convert", lambda *a: pytest.fail("файл с паролем ушел в конвертер"))
    src = tmp_path / "locked.ppt"
    src.write_bytes(OLE_HEADER + tail)
    with pytest.raises(ConvertError, match="паролем"):
        with PPT.as_new(src):
            pass


def test_unprotected_current_user_is_converted(tmp_path, fake_converter):
    src = tmp_path / "plain.ppt"
    src.write_bytes(OLE_HEADER + CURRENT_USER + b"\x5f\xc0\x91\xe3")
    with PPT.as_new(src) as converted:
        assert PPTX.texts(converted) == ["Почта sokolova@example.ru"]


def test_missing_converter_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "find_soffice", lambda path=None: None)
    monkeypatch.setattr(legacy, "pywin32_available", lambda: False)
    with pytest.raises(ConvertError, match="LibreOffice"):
        with PPT.as_new(_ole(tmp_path / "a.ppt")):
            pass


def test_cli_masks_ppt_into_ppt(tmp_path, fake_converter):
    src = _ole(tmp_path / "deck.ppt")
    assert _run_cli(["mask", str(src), "--types", "EMAIL", "--no-ner"]) == 0
    assert (tmp_path / "deck.masked.ppt").read_bytes()[:8] == OLE_HEADER[:8]
    assert fake_converter["to_ppt"] == ["Почта user1@example.com"]
    assert (tmp_path / "deck.mapping.json").exists()


def test_cli_masks_ppt_into_pptx_by_output_name(tmp_path, fake_converter):
    src = _ole(tmp_path / "deck.ppt")
    out = tmp_path / "deck.masked.pptx"
    assert _run_cli(["mask", str(src), "--types", "EMAIL", "--no-ner", "-o", str(out)]) == 0
    assert PPTX.texts(out) == ["Почта user1@example.com"]
    assert "to_ppt" not in fake_converter


def test_cli_unmasks_ppt_into_ppt(tmp_path, fake_converter):
    masked = _pptx(tmp_path / "deck.masked.ppt", [_slide(_shape([_para(["Почта user1@example.com"])]))])
    mp = tmp_path / "deck.mapping.json"
    mp.write_text(json.dumps({"version": 1, "labels": {"user1@example.com": {
        "type": "EMAIL", "original": "sokolova@example.ru", "key": "sokolova@example.ru", "n": 1}}},
        ensure_ascii=False), encoding="utf-8")
    assert _run_cli(["unmask", str(masked), "--mapping", str(mp)]) == 0
    assert (tmp_path / "deck.unmasked.ppt").read_bytes()[:8] == OLE_HEADER[:8]
    assert fake_converter["to_ppt"] == ["Почта sokolova@example.ru"]


def test_cli_refuses_to_overwrite_source(tmp_path, fake_converter, capsys):
    src = _ole(tmp_path / "a.ppt")
    assert _run_cli(["mask", str(src), "-o", str(src)]) == 2
    assert "один и тот же путь" in capsys.readouterr().err
    assert src.read_bytes() == OLE_HEADER
