"""Тип улицы и "д." - отдельные слова, а не буквы внутри слова.

Поймано на проверке карт: "штрихкод 4607001234566" маскировался адресом. Перенос
между частями адреса допускает ноль пробелов, и "ш" из "штрихкод" читалось как
"шоссе", "трихко" - как название, а последняя "д" - как "дом".
"""
import pytest

from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(types=("ADDRESS",), ner=False).mask(text)[0]


@pytest.mark.parametrize("src", [
    "штрихкод 4607001234566",
    "Штрихкод 4600000000000",
    "код 12, кв 3",
    "Каракаш д 5",
    "площадка 3 д 5",
])
def test_letters_inside_word_are_not_address(src):
    assert _mask(src) == src


@pytest.mark.parametrize("src", [
    "ш. Энтузиастов д 5",
    "Энтузиастов ш., д. 5",
    "ул.Ленина,д.5",
    "Тверская ул. д.5",
    "пр-кт Мира д 10 корп 2",
    "пер. Хлебный, д. 7",
    "д. 35, кв. 47",
])
def test_real_addresses_still_masked(src):
    assert _mask(src) == "{{ADDRESS_1}}"
