"""Стаж работы и службы. Требование вакансии ("стаж не менее 3 лет") - не сведения
о человеке: цифра должна стоять сразу за подписью."""
import pytest

from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(ner=False).mask(text)[0]


@pytest.mark.parametrize("src, expected", [
    ("стаж 12 лет", "стаж {{PERSONAL_1}}"),
    ("трудовой стаж: 12 лет 3 мес. 5 дн.", "трудовой стаж: {{PERSONAL_1}}"),
    ("страховой стаж 15 лет 2 месяца", "страховой стаж {{PERSONAL_1}}"),
    ("Иванов И.И., со стажем 7 лет", "{{PERSON_1}}, со стажем {{PERSONAL_1}}"),
    ("стаж работы в должности 5 лет", "стаж работы в должности {{PERSONAL_1}}"),
    ("общий стаж — 20 лет", "общий стаж — {{PERSONAL_1}}"),
    ("стаж 8 месяцев", "стаж {{PERSONAL_1}}"),
    ("выслуга лет 25 лет", "выслуга лет {{PERSONAL_1}}"),
    ("педагогический стаж: 10 л. 4 м.", "педагогический стаж: {{PERSONAL_1}}"),
])
def test_experience_masked(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "стаж не менее 3 лет",                  # требование вакансии
    "требуется стаж от 3 лет",
    "стаж работы более 5 лет",
    "стажировка 3 месяца",
    "стаж учитывается при расчете пенсии",
])
def test_experience_lookalikes_untouched(src):
    assert _mask(src) == src
