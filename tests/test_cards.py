"""Карта: номер, скрытый частично, последние 4 цифры, срок действия, держатель.

Полный номер с алгоритмом Луна и магнитная полоса проверяются в test_recognizers и
test_secrets. Номера в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(ner=False).mask(text)[0]


# --- номер, скрытый частично ---

@pytest.mark.parametrize("src", [
    "2200 00** **** 1234",
    "220000******1234",
    "4276 38** **** 5679",
    "4276 **** **** 5679",
    "**** **** **** 5679",
    "4276XXXXXXXX5679",
    "4276 38XX XXXX 5679",
    "XXXX-XXXX-XXXX-5679",
])
def test_masked_card_number(src):
    assert _mask(src) == "{{CARD_1}}"


def test_masked_card_one_label_for_both_spellings():
    assert _mask("2200 00** **** 1234 и снова 220000******1234") == \
        "{{CARD_1}} и снова {{CARD_1}}"


# --- последние 4 цифры ---

@pytest.mark.parametrize("src, expected", [
    ("****5679", "{{CARD_1}}"),                                  # 4 звездочки - карта и без подписи
    ("карта *5679", "карта {{CARD_1}}"),
    ("карта ••5679", "карта {{CARD_1}}"),
    ("карта Visa ···· 5679", "карта Visa {{CARD_1}}"),
    ("по карте MIR-5679", "по карте MIR-{{CARD_1}}"),
    ("карта, оканчивающаяся на 5679", "карта, оканчивающаяся на {{CARD_1}}"),
    ("последние 4 цифры карты 5679", "последние 4 цифры карты {{CARD_1}}"),
])
def test_card_last_four(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "*5679",                               # одна звездочка без карты - сноска или код
    "сноска *1234 в тексте",
    "последние 4 цифры паспорта 5679",
])
def test_last_four_without_card_untouched(src):
    assert _mask(src) == src


# --- срок действия ---

@pytest.mark.parametrize("src, expected", [
    ("срок действия карты 12/2027", "срок действия карты {{DATE_1}}"),
    ("valid thru 12/27", "valid thru {{DATE_1}}"),
    ("exp 12/27", "exp {{DATE_1}}"),
    ("Exp. date: 12/27", "Exp. date: {{DATE_1}}"),
    ("карта действует до 12/27", "карта действует до {{DATE_1}}"),
    # общая подпись - при номере карты в тексте
    ("карта 4276 3800 1234 5679, действует до 12/27", "карта {{CARD_1}}, действует до {{DATE_1}}"),
])
def test_card_expiry(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "действует до 12/27",                  # без карты - срок чего угодно
    "годна до 12/27",
    "срок 12/27",
    "export 12/27",
])
def test_expiry_without_card_untouched(src):
    assert _mask(src) == src


# --- держатель карты ---

@pytest.mark.parametrize("src, expected", [
    ("держатель карты: IVAN IVANOV", "держатель карты: {{PERSON_1}}"),
    ("Cardholder: IVAN IVANOV", "Cardholder: {{PERSON_1}}"),
    ("имя на карте: IVAN IVANOV", "имя на карте: {{PERSON_1}}"),
    ("Name on card: John Smith", "Name on card: {{PERSON_1}}"),
    ("Держатель карты: Иванов Иван Иванович", "Держатель карты: {{PERSON_1}}"),
])
def test_cardholder_name(src, expected):
    assert _mask(src) == expected


def test_holder_without_card_word_untouched():
    """"Держатель" без "карты" - и держатель ценных бумаг, им бывает организация."""
    assert _mask("держатель: ООО Ромашка") == "держатель: ООО Ромашка"
