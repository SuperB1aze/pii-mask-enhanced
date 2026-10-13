"""Подробности, которые ПД только рядом с найденным: дата рождения, дата и орган выдачи
документа, код подразделения, срок карты.

Дата сама по себе не ПД - без нее бухгалтерский документ теряет смысл. Поэтому дата
закрывается только у подписи ("дата рождения", "срок действия") или сразу за паспортом,
документом или картой. Данные в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.engine.core import Masker


def _mask(text: str, preset: str | None = None) -> str:
    types = presets.get(preset).types if preset else Masker().types
    return Masker(types=tuple(types), ner=False).mask(text)[0]


# --- дата рождения ---

@pytest.mark.parametrize("preset", [None, "accounting"])
@pytest.mark.parametrize("src, expected", [
    ("Дата рождения: 26.03.1997", "Дата рождения: {{DATE_1}}"),
    ("родилась 26 марта 1997 года", "родилась {{DATE_1}}"),
    ("дата рожд. 01.02.1985", "дата рожд. {{DATE_1}}"),
    ("г.р. 1985", "г.р. {{DATE_1}}"),
    ("Иванова, 1985 г.р., Москва", "Иванова, {{DATE_1}} г.р., Москва"),
])
def test_birth_date(src, expected, preset):
    """Дата рождения закрывается и без набора: тип DATE берет только даты рядом с ПД."""
    assert _mask(src, preset) == expected


# --- дата и орган выдачи, код подразделения ---

@pytest.mark.parametrize("src, expected", [
    ("паспорт 4509 123456 выдан 12.03.2015 ОУФМС России по г. Москве",
     "паспорт {{PASSPORT_1}} выдан {{DATE_1}} {{ISSUER_1}}"),
    ("паспорт 4509 123456, выдан ОВД района Арбат г. Москвы 12 марта 2015 г., "
     "код подразделения 770-001",
     "паспорт {{PASSPORT_1}}, выдан {{ISSUER_1}} {{DATE_1}}, код подразделения {{ISSUER_2}}"),
    ("загранпаспорт 75 1234567 выдан 01.02.2020 МВД 77001",
     "загранпаспорт {{IDDOC_1}} выдан {{DATE_1}} {{ISSUER_1}}"),
    ("ПТС 77 УО 123456, выдан МОТН и РАС ГИБДД УВД по ЮАО г. Москвы 15.03.2021",
     "ПТС {{IDDOC_1}}, выдан {{ISSUER_1}} {{DATE_1}}"),
])
def test_issue_details_after_document(src, expected):
    assert _mask(src) == expected


def test_issue_fields_of_a_form():
    """В анкете дата выдачи и орган - отдельные поля, а не продолжение номера."""
    src = ("Паспорт: 4509 123456\nДата выдачи: 12.03.2015\n"
           "Кем выдан: ОУФМС России по г. Москве\nКод подразделения: 770-001")
    assert _mask(src) == ("Паспорт: {{PASSPORT_1}}\nДата выдачи: {{DATE_1}}\n"
                          "Кем выдан: {{ISSUER_1}}\nКод подразделения: {{ISSUER_2}}")


def test_unit_code_without_passport():
    assert _mask("код подразделения 770-001") == "код подразделения {{ISSUER_1}}"


# --- срок карты ---

@pytest.mark.parametrize("src, expected", [
    ("карта 4276 3800 1234 5679, срок 12/27", "карта {{CARD_1}}, срок {{DATE_1}}"),
    ("карта 4276 3800 1234 5679 12/2027", "карта {{CARD_1}} {{DATE_1}}"),
    ("Номер карты: 4276 3800 1234 5679\nСрок действия: 12/27",
     "Номер карты: {{CARD_1}}\nСрок действия: {{DATE_1}}"),
    ("valid thru 12/27 у карты 4276 3800 1234 5679", "valid thru {{DATE_1}} у карты {{CARD_1}}"),
])
def test_card_expiry(src, expected):
    assert _mask(src) == expected


# --- даты, которые не ПД ---

@pytest.mark.parametrize("src", [
    "Период с 01.01.2025 по 31.03.2025, оплата 15.02.2025",
    "товар выдан 12.03.2015 со склада",           # "выдан" без документа
    "Дата выдачи груза: 12.03.2015",              # подпись без паспорта в тексте
    "срок 12/27 дней",                            # "ММ/ГГ" без карты
    "в 1985 году",
    "500 гр. сахара",
])
def test_dates_without_personal_data_untouched(src):
    assert _mask(src) == src


def test_contract_term_is_not_card_expiry():
    """У подписи где угодно в тексте берется только "ММ/ГГ": "до 31.12.2026" - срок договора."""
    out = _mask("карта 4276 3800 1234 5679. Договор действует до 31.12.2026")
    assert "31.12.2026" in out


def test_contract_date_masked_by_default():
    """Дата договора раньше закрывалась только с набором."""
    assert "01.02.2020" not in _mask("ДБО № 12345 от 01.02.2020")


def test_roundtrip_and_idempotent():
    m = Masker(ner=False)
    src = "паспорт 4509 123456 выдан 12.03.2015 ОУФМС России по г. Москве, код подразделения 770-001"
    masked, mapping = m.mask(src)
    assert m.unmask(masked, mapping) == src
    assert m.mask(masked, mapping)[0] == masked
