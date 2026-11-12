"""Публичный API: mask_file и unmask_file выбирают формат по расширению."""
from __future__ import annotations

import pytest

from pii_mask_enhanced import MaskError, Options, mask_file, mask_text, unmask_file, unmask_text
from pii_mask_enhanced.audit.base import AuditError, Auditor
from pii_mask_enhanced.formats.word import DOCX
from test_docx import _docx, _para

NO_NER = Options(ner=False)


class _DownAuditor(Auditor):
    def available(self) -> bool:
        return False

    def find(self, masked_text):
        return []


class _FindAuditor(Auditor):
    def available(self) -> bool:
        return True

    def find(self, masked_text):
        return [("Марципан", "SECRET")] if "Код доступа" in masked_text else []


class _FailSecondAuditor(Auditor):
    def __init__(self):
        self.calls = 0

    def available(self) -> bool:
        return True

    def find(self, masked_text):
        self.calls += 1
        if self.calls == 1:
            return [("Марципан", "SECRET")]
        raise AuditError("ошибка второго блока")


def test_text_round_trip(tmp_path):
    src = tmp_path / "заметка.txt"
    src.write_text("Телефон +7 916 555-12-34", encoding="utf-8")
    masked = tmp_path / "заметка.masked.txt"
    mapping = mask_file(src, masked, NO_NER)
    assert "+7 000 000-00-01" in masked.read_text(encoding="utf-8")
    restored = tmp_path / "заметка.unmasked.txt"
    unmask_file(masked, restored, mapping)
    assert restored.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_docx_round_trip(tmp_path):
    src = _docx(tmp_path / "a.docx", [_para(["Почта sokolova@example.ru"])])
    masked = tmp_path / "a.masked.docx"
    mapping = mask_file(src, masked, NO_NER)
    assert DOCX.texts(masked) == ["Почта user1@example.com"]
    restored = tmp_path / "a.unmasked.docx"
    unmask_file(masked, restored, mapping)
    assert DOCX.texts(restored) == DOCX.texts(src)


def test_mapping_is_continued(tmp_path):
    _, mapping = mask_text("Почта sokolova@example.ru", NO_NER)
    src = tmp_path / "b.txt"
    src.write_text("Пишите на ivanov@example.ru или sokolova@example.ru", encoding="utf-8")
    mapping = mask_file(src, tmp_path / "b.masked.txt", NO_NER, mapping)
    assert len(mapping["labels"]) == 2
    assert unmask_text("user1@example.com", mapping) == "sokolova@example.ru"


def test_preset_notes_go_to_report(tmp_path):
    notes = []
    mask_text("Телефон +7 916 555-12-34", Options(preset="auto", ner=False), report=notes.append)
    assert notes


def test_same_path_refused(tmp_path):
    src = tmp_path / "c.txt"
    src.write_text("текст", encoding="utf-8")
    with pytest.raises(MaskError, match="один и тот же путь"):
        mask_file(src, src, NO_NER)
    assert src.read_text(encoding="utf-8") == "текст"


def test_unknown_preset_is_mask_error(tmp_path):
    src = tmp_path / "d.txt"
    src.write_text("текст", encoding="utf-8")
    with pytest.raises(MaskError):
        mask_file(src, tmp_path / "d.masked.txt", Options(preset="нет-такого"))


def test_auditor_masks_docx_text_and_keeps_mapping(tmp_path):
    src = _docx(tmp_path / "e.docx", [_para(["Код доступа: Марципан"]),
                                        _para(["Десерт: Марципан"])])
    dst = tmp_path / "e.masked.docx"
    mapping = mask_file(src, dst, NO_NER, auditor=_FindAuditor())
    assert DOCX.texts(dst) == ["Код доступа: {{SECRET_1}}", "Десерт: Марципан"]
    assert mapping["labels"]["{{SECRET_1}}"]["original"] == "Марципан"


def test_unavailable_auditor_is_mask_error(tmp_path):
    src = tmp_path / "f.txt"
    src.write_text("Телефон +7 916 555-12-34", encoding="utf-8")
    with pytest.raises(MaskError):
        mask_file(src, tmp_path / "f.masked.txt", NO_NER, auditor=_DownAuditor())


def test_unavailable_auditor_does_not_write_office_output(tmp_path):
    src = _docx(tmp_path / "g.docx", [_para(["обычный текст"])])
    dst = tmp_path / "g.masked.docx"
    with pytest.raises(MaskError, match="аудитор недоступен"):
        mask_file(src, dst, NO_NER, auditor=_DownAuditor())
    assert not dst.exists()


def test_office_audit_failure_does_not_write_output_or_mutate_mapping(tmp_path):
    src = _docx(tmp_path / "h.docx", [
        _para(["Код доступа: Марципан"]),
        _para(["Второй блок без найденных данных"]),
    ])
    dst = tmp_path / "h.masked.docx"
    mapping = {"version": 1, "labels": {}}

    with pytest.raises(MaskError, match="ошибка второго блока"):
        mask_file(src, dst, NO_NER, mapping, auditor=_FailSecondAuditor())

    assert mapping == {"version": 1, "labels": {}}
    assert not dst.exists()
