"""Код инвестора: УКК и торговый код.

Формат свой у каждого брокера и биржи, поэтому код берется по подписи - в строке
или в соседней ячейке. Без подписи узнается только торговый код фондового рынка
Мосбиржи: "MC" и 10 цифр. Коды в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats.common.office_xml import cell_label_type

from masking import mask as _mask


@pytest.mark.parametrize("src,expected", [
    ("УКК: 123456", "УКК: {{INVESTOR_1}}"),
    ("УКК 7A9B12", "УКК {{INVESTOR_1}}"),
    ("Уникальный код клиента (УКК): 123456", "Уникальный код клиента (УКК): {{INVESTOR_1}}"),
    ("Торговый код: MC0123400000", "Торговый код: {{INVESTOR_1}}"),
    ("торговый код клиента на фондовом рынке: AB0012", "торговый код клиента на фондовом рынке: {{INVESTOR_1}}"),
    ("Код инвестора 4567-ФР", "Код инвестора {{INVESTOR_1}}"),
    ("код клиента: 00-000123", "код клиента: {{INVESTOR_1}}"),
    ("Клиентский код 98765.", "Клиентский код {{INVESTOR_1}}."),
])
def test_code_by_label(src, expected):
    assert _mask(src) == expected


def test_code_taken_whole():
    """Огрызок за маской выдает код не хуже полного."""
    assert _mask("Код клиента в торговой системе L01+00000F00") == \
        "Код клиента в торговой системе {{INVESTOR_1}}"


@pytest.mark.parametrize("code", ["MC0123400000", "МС0123400000"])   # латиница и кириллица
def test_moex_code_without_label(code):
    assert _mask(f"сделка по коду {code}") == "сделка по коду {{INVESTOR_1}}"


def test_labelled_code_masked_everywhere():
    out = _mask("УКК 123456. В отчете за март клиент 123456 упомянут снова")
    assert "123456" not in out
    assert out.count("{{INVESTOR_1}}") == 2


@pytest.mark.parametrize("src", [
    "торговый код присваивается биржей",
    "кодекс клиента банка 2020",
    "код клиента отсутствует",
    "по ст. 158 УК РФ",
    "MC01234",
    "УКК: 123456789012345678901234567890",
])
def test_lookalikes_untouched(src):
    assert _mask(src) == src


def test_roundtrip_and_idempotent():
    """Имя типа без "_": иначе метку не узнают ни unmask, ни повторный mask."""
    m = Masker(ner=False)
    src = "Торговый код: MC0123400000"
    masked, mapping = m.mask(src)
    assert m.unmask(masked, mapping) == src
    again, _ = m.mask(masked, mapping)
    assert again == masked


@pytest.mark.parametrize("label,value,expected", [
    ("Торговый код", "MC0123400000", "INVESTOR"),
    ("УКК:", "123456", "INVESTOR"),
    ("Уникальный код клиента (УКК)", "7A9B12", "INVESTOR"),
    ("Код клиента", "отсутствует", None),
])
def test_cell_label(label, value, expected):
    assert cell_label_type(label, value) == expected
