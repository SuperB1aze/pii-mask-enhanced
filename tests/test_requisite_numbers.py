"""Номера без подписи: кадастровый номер, БИК, КПП, даты. Номера в тестах выдуманные."""
import pytest

from pii_mask_enhanced.detection.recognizers.finders import numbers
from pii_mask_enhanced.detection.recognizers.validators import Validator
from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(ner=False).mask(text)[0]


def _texts(finder, text: str) -> list[str]:
    return [e.text for e in finder(text)]


# --- кадастровый номер ---

@pytest.mark.parametrize("src, expected", [
    ("Кадастровый номер 77:01:0001001:1234", ["77:01:0001001:1234"]),
    ("участок 50:21:110101:15, соседний 50:21:110101:16", ["50:21:110101:15", "50:21:110101:16"]),
])
def test_kadastr_found(src, expected):
    assert _texts(numbers.kadastr_numbers, src) == expected


@pytest.mark.parametrize("src", [
    "время 12:30:45",
    "12:34:567890",            # три части - не кадастровый номер
    "1:23:45:1234567:8",       # часть более длинной цепочки
    "77:01:0001001:1234:5",
])
def test_kadastr_lookalikes_ignored(src):
    assert numbers.kadastr_numbers(src) == []


def test_kadastr_masked_with_one_label():
    src = "Кадастровый номер 77:01:0001001:1234, повторно 77:01:0001001:1234"
    assert _mask(src) == ("Кадастровый номер {{KADASTR_NUMBER_1}}, "
                          "повторно {{KADASTR_NUMBER_1}}")


def test_time_untouched():
    assert _mask("встреча в 12:30:45") == "встреча в 12:30:45"


# --- БИК и КПП ---

def test_bik_found():
    ents = numbers.biks("БИК 044525225, КПП 770101001")
    assert [(e.type, e.text) for e in ents] == [("BIK", "044525225")]


@pytest.mark.parametrize("src", ["0445252250", "А044525225", "12044525225"])
def test_bik_only_as_separate_word(src):
    assert numbers.biks(src) == []


def test_kpp_found():
    assert _texts(numbers.kpps, "КПП 770101001") == ["770101001"]


@pytest.mark.parametrize("src", ["7701010011", "A770101001"])
def test_kpp_only_as_separate_word(src):
    assert numbers.kpps(src) == []


@pytest.mark.parametrize("num, ok", [("770101001", True), ("77010100", False),
                                     ("7701010011", False)])
def test_kpp_ok(num, ok):
    assert Validator.kpp_ok(num) is ok


# --- даты ---

@pytest.mark.parametrize("src", ["«5» марта 2024 года", "5 марта 2024 года", "05.03.2024"])
def test_date_found(src):
    assert _texts(numbers.dates, src) == [src]


@pytest.mark.parametrize("src", [
    "5 марта 2024",            # без "года"
    "32.01.2024",
    "05.13.2024",
    "105.03.2024",
])
def test_date_lookalikes_ignored(src):
    assert numbers.dates(src) == []
