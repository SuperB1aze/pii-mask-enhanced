"""Разметка не должна прятать сущности от NER.

Найдено на живом резюме 06.08.2026: строка "# Имя Фамилия" проходила маскировку
насквозь - slovnet не размечал НИ ОДНОЙ сущности, хотя без решеток имя ловилось.
Особенно опасно потому, что резюме в markdown начинается ровно с такой строки.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker

NAME = "Смирнова Анна Валерьевна"

# Слева - как имя обернуто в документе, справа - обязано ли оно исчезнуть.
WRAPPERS = [
    "{n}",
    "# {n}",
    "## {n}",
    "#{n}",
    "#### {n}",
    "  # {n}",
    "## {n} ##",
    "**{n}**",
    "- {n}",
    "+ {n}",
    "* {n}",
    "> {n}",
    "1. {n}",
    "1) {n}",
    "- [ ] {n}",
    "| {n} |",
    "`{n}`",
    "Резюме: {n}",
]


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_name_masked_and_markup_survives(wrapper):
    """Имя уходит под маску, а сама разметка остается - документ должен остаться документом.

    Проверки идут вместе: сравнение формы в одиночку проходит и тогда, когда
    маскировка не сработала вовсе - заменять в тексте нечего, и он равен исходному.
    """
    src = wrapper.format(n=NAME)
    masked, _ = Masker().mask(src)
    assert "Смирнов" not in masked, f"имя утекло из {wrapper!r}: {masked!r}"
    assert "{{PERSON_1}}" in masked
    restored_shape = masked.replace("{{PERSON_1}}", NAME)
    assert restored_shape == src, f"разметка поехала: {src!r} -> {masked!r}"


def test_offsets_stay_aligned_in_mixed_document():
    """Спаны берутся из теневой копии - проверяем, что они не поехали в оригинале."""
    src = f"# {NAME}\n\n| Город | Москва |\n\nТелефон: +7 (912) 3456789\n"
    masked, mapping = Masker().mask(src)
    assert "Смирнов" not in masked
    assert "+7 (912) 3456789" not in masked
    assert masked.startswith("# {{PERSON_1}}")
    assert "| Город |" in masked          # структура таблицы цела
    person = next(v for v in mapping["labels"].values() if v["type"] == "PERSON")
    # в mapping не должно быть пробелов вместо разметки - там текст из оригинала
    assert "#" not in person["original"] and "  " not in person["original"]
    assert person["original"].split()[1:] == ["Анна", "Валерьевна"]


def test_caps_name_without_patronymic():
    """Регулярка держится на отчестве; пара слов капсом без него - работа NER
    по нормализованному регистру."""
    masked, _ = Masker().mask("в выборке ВЕРШКОВА ГАЛИНА указана дважды")
    assert "ВЕРШКОВА" not in masked and "ГАЛИНА" not in masked
