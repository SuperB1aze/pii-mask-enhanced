"""Дата смерти, паспорт РФ, СНИЛС: варианты записи, которые раньше уходили наружу.

Данные в тестах выдуманные; СНИЛС 112-233-445 95 проходит контрольную сумму.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(ner=False).mask(text)[0]


# --- дата смерти: как дата рождения, только у подписи или глагола ---

@pytest.mark.parametrize("src, expected", [
    ("дата смерти 01.02.2020", "дата смерти {{DATE_1}}"),
    ("дата смерти: 01.02.2020", "дата смерти: {{DATE_1}}"),
    ("умер 01.02.2020", "умер {{DATE_1}}"),
    ("умерла 1 февраля 2020 года", "умерла {{DATE_1}}"),
    ("скончался 01.02.2020", "скончался {{DATE_1}}"),
    ("дата кончины 01.02.2020", "дата кончины {{DATE_1}}"),
    ("погиб 01.02.2020", "погиб {{DATE_1}}"),
    ("ум. 01.02.2020", "ум. {{DATE_1}}"),
    ("год смерти 2020", "год смерти {{DATE_1}}"),
    ("умер в 2020 году", "умер в {{DATE_1}} году"),
    # годы жизни рядом с ФИО
    ("Иванов И.И. (1950-2020)", "{{PERSON_1}} {{PERSONAL_1}}"),
])
def test_death_date_masked(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "срок истек 01.02.2020",                 # дата без подписи - основа смысла текста
    "(1950–2020) годы",                      # без человека рядом - просто период
])
def test_date_without_death_untouched(src):
    assert _mask(src) == src


# --- паспорт РФ ---

@pytest.mark.parametrize("src, expected", [
    ("паспорт 4510123456", "паспорт {{PASSPORT_1}}"),
    ("паспорт гражданина РФ 4510123456", "паспорт гражданина РФ {{PASSPORT_1}}"),
    ("ДУЛ: 4510123456", "ДУЛ: {{PASSPORT_1}}"),
    ("паспорт 4510-123456", "паспорт {{PASSPORT_1}}"),
    ("Паспорт гражданина Российской Федерации: 4510 123456",
     "Паспорт гражданина Российской Федерации: {{PASSPORT_1}}"),
])
def test_passport_spellings(src, expected):
    assert _mask(src) == expected


def test_solid_ten_digits_after_inn_stays_inn():
    """Слитные 10 цифр - и ИНН: без слова паспорта прямо перед ними паспортом не считаем."""
    assert _mask("паспорт выдан, ИНН 7701234567") == "паспорт выдан, ИНН {{INN_1}}"


def test_citizenship_still_masked_outside_passport_name():
    """"паспорт гражданина РФ" - название документа, а "гражданин РФ" - сведения о человеке."""
    assert _mask("гражданин РФ") == "гражданин {{PERSONAL_1}}"


# --- СНИЛС ---

@pytest.mark.parametrize("src, expected", [
    ("СНИЛС 112 233 445 95", "СНИЛС {{SNILS_1}}"),
    ("112 233 445 95", "{{SNILS_1}}"),            # без подписи - по контрольной сумме
])
def test_snils_with_spaces(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "112 233 445 96",                            # сумма не сходится
    "112-233 445 95",                            # разделители между тройками разные
    "11223344595",                               # слитно без подписи - и телефон
])
def test_snils_lookalikes_untouched(src):
    assert _mask(src) == src
