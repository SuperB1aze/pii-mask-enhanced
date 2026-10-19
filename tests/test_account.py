"""Номер банковского счета: 20 цифр у подписи или по структуре номера.

Подпись - в той же строке или в соседней ячейке таблицы. Без подписи 20 цифр - это
и КБК, и УИН, поэтому счет берется по плану счетов ЦБ (балансовый счет и код валюты)
или по контрольному ключу с БИК из текста. Номера в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.detection.recognizers.recognizers import find_format_entities
from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats.office_xml import cell_label_type, numbers_after_labels

ACC = "40817810099910004312"


def _accounts(text: str) -> list[str]:
    return [e.text for e in find_format_entities(text) if e.type == "ACCOUNT"]


@pytest.mark.parametrize("label", [
    "р/с", "Р/С №", "к/с", "р/сч", "Сч. №", "Счет №", "счета", "на счет",
    "номер счета:", "Расчетный счет:", "расчётный счёт", "Корр. счет", "корр.счет",
    "лицевой счет", "счет получателя", "Р/с\n",
])
def test_account_labels(label):
    assert _accounts(f"{label} {ACC}") == [ACC]


@pytest.mark.parametrize("raw", [
    "4081 7810 0999 1000 4312",
    "40817 810 0 9991 0004312",
    "40817.810.0.9991.0004312",
])
def test_account_in_groups(raw):
    assert _accounts(f"р/с {raw}") == [raw]


def test_grouped_and_solid_one_label():
    out = Masker(ner=False).mask(f"р/с {ACC}, он же р/с 4081 7810 0999 1000 4312")[0]
    assert out == "р/с {{ACCOUNT_1}}, он же р/с {{ACCOUNT_1}}"


def test_account_followed_by_other_number():
    """В строке реквизитов за счетом через пробел идет БИК - счет все равно берется."""
    assert _accounts(f"р/с {ACC} 044525225") == [ACC]


@pytest.mark.parametrize("src, raw", [
    (f"переведите на {ACC} до пятницы", ACC),        # счет физлица
    (ACC, ACC),
    ("40817 810 0 9991 0004312", "40817 810 0 9991 0004312"),
    ("40702810400000012345", "40702810400000012345"),  # счет организации
    ("30101810400000000225", "30101810400000000225"),  # корсчет
    ("42301810500000123456", "42301810500000123456"),  # вклад
])
def test_account_without_label_by_structure(src, raw):
    assert _accounts(src) == [raw]


def test_account_without_label_by_bik_key():
    """Балансового счета 603 нет в справочнике, но ключ по БИК из текста сходится."""
    assert _accounts("БИК 044525225, получатель 60311810900000001234") == \
        ["60311810900000001234"]


def test_bare_and_labelled_account_one_label():
    out = Masker(ner=False).mask(f"перевод на {ACC}, позже р/с {ACC}")[0]
    assert out == "перевод на {{ACCOUNT_1}}, позже р/с {{ACCOUNT_1}}"


@pytest.mark.parametrize("src", [
    f"р/с {ACC}1",                                  # 21 цифра - не счет
    f"{ACC}345",
    "КБК 18210102010011000110",
    "УИН 18810177200001234567",
    "штрихкод 46070012345660000000",
    "12345678901234567890",
    "получатель 60311810900000001234",              # ни справочника, ни БИК
    "БИК 044525225, получатель 60311810000000001234",  # ключ не сходится
])
def test_not_an_account(src):
    assert _accounts(src) == []


def test_account_masked_by_default():
    """Счет - прямой идентификатор, маскируется и без набора."""
    assert Masker(ner=False).mask(f"р/с {ACC}")[0] == "р/с {{ACCOUNT_1}}"


def test_invoice_word_does_not_steal_account():
    """"Счет № 40817..." - номер счета, а не номер документа "счет"."""
    masker = Masker(types=presets.get("accounting").types, ner=False)
    assert masker.mask(f"Счет № {ACC}")[0] == "Счет № {{ACCOUNT_1}}"


# --- подпись в соседней ячейке ---

@pytest.mark.parametrize("label,value,expected", [
    ("Р/с", ACC, "ACCOUNT"),
    ("Расчетный счет:", "4081 7810 0999 1000 4312", "ACCOUNT"),
    ("Счет", "12345", None),            # в ведомости под "Счет" - номера документов
    ("КПП", "770101001", "KPP"),
    ("ИНН", "7707083893", "INN"),
    ("Итого", ACC, None),
])
def test_cell_label_type(label, value, expected):
    assert cell_label_type(label, value) == expected


def test_numbers_after_labels_in_word_table():
    values = ["Р/с", ACC, "КПП", "770101001", "Сумма", "15000"]
    # тип и ключ - как у находки в тексте: счет по цифрам
    assert numbers_after_labels(values) == {ACC: ("ACCOUNT", ACC), "770101001": ("KPP", "770101001")}
