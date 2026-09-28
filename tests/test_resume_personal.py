"""Личные данные из шапки резюме: дата рождения, город, ложная география.

hh-резюме начинается строкой "Женщина, 29 лет, родилась 26 марта 1997" и
строкой "Проживает: Екатеринбург". Дата рождения - прямой идентификатор, а
связка "город плюс узкая должность" сужает человека до единиц; при этом адрес
в других документах мы маскируем, а эти два поля проходили мимо.
"""
from pii_mask.core import Masker


def mask(text, **kw):
    return Masker(**kw).mask(text)[0]


def test_birth_date_is_masked():
    out = mask("Женщина, 29 лет, родилась 26 марта 1997", types=("DATE",))
    assert "26 марта 1997" not in out, out


def test_birth_date_in_digits():
    out = mask("Дата рождения: 26.03.1997", types=("DATE",))
    assert "26.03.1997" not in out, out


def test_work_period_is_not_a_birth_date():
    """Даты опыта работы трогать нельзя - без них резюме нечитаемо."""
    out = mask("Октябрь 2020 — Январь 2026, дата-инженер. Опыт работы 6 лет",
               types=("DATE",))
    assert "Октябрь 2020" in out and "Январь 2026" in out, out


def test_city_of_residence_is_masked():
    out = mask("Проживает: Екатеринбург\nНе готова к переезду", types=("ADDRESS",))
    assert "Екатеринбург" not in out, out


def test_city_inside_a_company_name_survives():
    """Якорь узкий: город маскируется только там, где он про человека."""
    out = mask("Работала в ООО «Екатеринбург-Строй» пять лет",
               types=("ADDRESS",), ner=False)
    assert "Екатеринбург-Строй" in out, out


def test_country_is_not_a_person():
    """"России" из названия вуза уходило в маску как персона."""
    out = mask("Уральский федеральный университет имени первого Президента России",
               types=("PERSON",))
    assert "{{PERSON" not in out, out


def test_geography_before_initials_is_not_a_surname():
    """"России Б.Н. Ельцина" - не ФИО: правило "Фамилия И.О." взяло страну.

    Спан приходит от форматного распознавателя, а не от NER, поэтому отсев
    географии нужен и на этом пути тоже.
    """
    out = mask("Университет имени первого Президента России Б.Н. Ельцина",
               types=("PERSON",))
    assert "{{PERSON_1}} Ельцина" not in out, out
    assert "России" in out, out
