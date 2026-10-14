"""Значения по подписи: ЕСИА ID, логин, полис, PIN, пароль, пол, гражданство...

Без подписи такое значение - просто число или слово, поэтому граница здесь - фразы,
где подпись есть, а значения нет: "логин выдается администратором", "пол деревянный".
Данные в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats.office_xml import cell_label_type


def _mask(text: str, preset: str | None = None) -> str:
    types = presets.get(preset).types if preset else Masker().types
    return Masker(types=tuple(types), ner=False).mask(text)[0]


@pytest.mark.parametrize("preset", [None, "accounting"])
@pytest.mark.parametrize("src, expected", [
    # идентификатор человека в системе
    ("ЕСИА ID: 1000123456", "ЕСИА ID: {{PERSON_ID_1}}"),
    ("Госуслуги идентификатор 1000123456", "Госуслуги идентификатор {{PERSON_ID_1}}"),
    ("MDM ID: 4567890123", "MDM ID: {{PERSON_ID_1}}"),
    ("таб. № 00123", "таб. № {{PERSON_ID_1}}"),
    ("логин: ivanov_i", "логин: {{PERSON_ID_1}}"),
    ("обращение № 2024-0012345 от клиента", "обращение № {{PERSON_ID_1}} от клиента"),
    ("карта лояльности 1234567890", "карта лояльности {{PERSON_ID_1}}"),
    ("полис ОМС 7700 0000 0000 0000", "полис ОМС {{PERSON_ID_1}}"),
    ("полис ОСАГО ХХХ 0123456789", "полис ОСАГО {{PERSON_ID_1}}"),
    ("листок нетрудоспособности № 910012345678", "листок нетрудоспособности № {{PERSON_ID_1}}"),
    ("счёт депо № 12345-Д", "счёт депо № {{PERSON_ID_1}}"),
    # секреты
    ("CVV: 123", "CVV: {{SECRET_1}}"),
    ("код на обороте 789", "код на обороте {{SECRET_1}}"),
    ("ПИН-код: 4821", "ПИН-код: {{SECRET_1}}"),
    ("пароль: Qwerty123!", "пароль: {{SECRET_1}}"),
    ("кодовое слово: Барсик", "кодовое слово: {{SECRET_1}}"),
    # сведения о человеке
    ("пол: жен.", "пол: {{PERSONAL_1}}"),
    ("гражданство: Республика Беларусь", "гражданство: {{PERSONAL_1}}"),
    ("гражданство РФ", "гражданство {{PERSONAL_1}}"),
    ("семейное положение: не замужем", "семейное положение: {{PERSONAL_1}}"),
    ("возраст: 38 лет", "возраст: {{PERSONAL_1}}"),
    ("ПКР 812", "ПКР {{PERSONAL_1}}"),
    # назначение платежа - целиком, вместе с тем, что внутри
    ("Назначение платежа: Оплата по счету 15 за услуги Иванова И.И., НДС не облагается",
     "Назначение платежа: {{PAYMENT_1}}"),
])
def test_value_after_label(src, expected, preset):
    assert _mask(src, preset) == expected


def test_citizenship_does_not_take_the_surname():
    """Страна - одно слово или устойчивое из двух; дальше уже фамилия."""
    assert _mask("гражданин Российской Федерации Белоусов") == "гражданин {{PERSONAL_1}} Белоусов"


def test_labelled_value_masked_everywhere():
    assert _mask("логин: ivanov_i. Вход под ivanov_i выполнен") == \
        "логин: {{PERSON_ID_1}}. Вход под {{PERSON_ID_1}} выполнен"


@pytest.mark.parametrize("src", [
    "логин выдается администратором",         # у логина и пароля нужен ":" или "="
    "пароль надо менять раз в квартал",
    "пол деревянный, 12 кв. м",                # "пол" без двоеточия - пол комнаты
    "пол: деревянный",                          # значения пола - закрытый список
    "гражданство и место жительства",           # без двоеточия - только название страны
    "семейное положение влияет на вычет",
    "через Госуслуги 15 дней",
    "MDM система 2.0",
    "PIN-код выдается в отделении",
    "в возрасте до 18 лет",
    "Обращение к руководителю",
])
def test_label_without_value_untouched(src):
    assert _mask(src) == src


@pytest.mark.parametrize("label, value, expected", [
    ("ЕСИА ID", "1000123456", "PERSON_ID"),
    ("Логин", "ivanov_i", "PERSON_ID"),
    ("Пол", "жен.", "PERSONAL"),
    ("Назначение платежа", "Оплата по счету 15", "PAYMENT"),
    ("Итого", "1000123456", None),
])
def test_cell_label(label, value, expected):
    """Подпись в соседней ячейке таблицы - как в анкете или выписке 1С."""
    assert cell_label_type(label, value) == expected


def test_roundtrip_and_idempotent():
    m = Masker(ner=False)
    src = "ЕСИА ID: 1000123456\nпароль: Qwerty123!\nНазначение платежа: Оплата по счету 15"
    masked, mapping = m.mask(src)
    assert m.unmask(masked, mapping) == src
    assert m.mask(masked, mapping)[0] == masked
