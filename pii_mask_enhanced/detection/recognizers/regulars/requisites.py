"""Реквизиты по подписи, номера документов и значения из registry/labelled_values."""
import re
from dataclasses import dataclass
from typing import Callable

from ...registry.entity_types import REQUISITE_WORD
from ...registry.labelled_patterns import (BALANCE_AMOUNT, BALANCE_LABEL, INCOME_AMOUNT,
                                           INCOME_LABEL)
from ...registry.labelled_values import VALUES
from .. import helpers
from ..entity import digits, text_key

_KPP_LETTERS = r"\d{4}(?-i:[A-ZА-ЯЁ]{2})\d{3}(?!\w)"

# Число рядом с подписью, без контрольной суммы. Пары "ИНН/КПП" - в PAIRED_REQUISITE_RE.
REQUISITE_RE = re.compile(
    rf"(?<![/\w])({REQUISITE_WORD}"
    r"|рег(?:истрационный)?\.?[ \t]*(?:номер|№))"
    rf"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*({_KPP_LETTERS}|\d{{3,15}})(?![ \t]*/[ \t]*\d)",
    re.IGNORECASE,
)

# "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку
PAIRED_REQUISITE_RE = re.compile(
    rf"({REQUISITE_WORD}(?:[ \t]*(?:/|и)[ \t]*{REQUISITE_WORD})+)"
    rf"[^\d\n]{{0,80}}?"
    rf"(\d{{3,15}}(?:[ \t]*/[ \t]*(?:{_KPP_LETTERS}|\d{{0,15}}))+)",
    re.IGNORECASE,
)

# "от 01.09.2026" за номером, найденным не через DOCREF_RE
DATE_AFTER_RE = re.compile(rf"[ \t]{{0,3}}от[ \t]{{0,3}}({helpers.DATE})", re.IGNORECASE)

DOCREF_RE = re.compile(
    rf"{helpers.DOC_ANCHOR}{helpers.DOC_GAP}"
    r"[ \t]{0,3}(№|N|N°)?[ \t]{0,3}"
    rf"(?<![\w-])(?!{helpers.DATE}(?![\w/-]))"
    r"([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/._]{1,30})"
    rf"(?:[ \t]{{1,3}}от[ \t]{{1,3}}({helpers.DATE}))?",
    re.IGNORECASE,
)
# обратный порядок: "акт от 01.03.2024 № 15", "Договор от 25.01.2023 № 12/24"; "№" обязателен
DOCREF_DATE_FIRST_RE = re.compile(
    rf"{helpers.DOC_ANCHOR}{helpers.DOC_GAP}[ \t]{{1,3}}от[ \t]{{1,3}}({helpers.DATE})"
    r"[ \t]{0,3}(?:г\.|года)?[ \t]{0,3}(?:№|N|N°)[ \t]{0,3}"
    r"([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/._]{0,30})",
    re.IGNORECASE,
)

# Номер из сегментов через "/" или "-": "12345/ФЛ", "ФЛ-12345", "625/0000-0123456 / ЮЛ"
DOC_SEGMENTS_RE = re.compile(
    r"(?<![\w./-])\w+(?:\.\w+)*(?:(?:-|[ \t]?/[ \t]?)\w+(?:\.\w+)*)+(?![\w/-])"
)
DOC_SEGMENT_SEP_RE = re.compile(r"[ \t]?[/-][ \t]?")

# номера, отделенные от слова фразой: "Лицензия на ... №1326"
DOC_REQUISITE_RES = (
    re.compile(r"(?:договор\w*|(?<!\w)ДБО)[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    # "КД № 625/0000-0123456": короткое сокращение - только со знаком номера сразу за ним
    re.compile(r"(?<!\w)КД[ \t]*№[ \t]*([\w/\-.]+)"),
    re.compile(r"соглашени\w*[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"(?:лицензи\w+|свидетельств\w+)[^№]{0,120}№[ \t]*(\d[\d-]{2,20})", re.IGNORECASE),
    re.compile(r"регистрационный[ \t\n]+номер[^:]{0,90}:[ \t\n]*(\d{3,15})", re.IGNORECASE),
)

# Документ гос. образца по "серия ... №": свидетельство, диплом, аттестат, удостоверение
GOVDOC_RE = re.compile(
    r"(?<!\w)сер(?:и[яиюей]|\.)[ \t\n]*"
    r"((?:\d{2,6}|(?-i:[А-ЯЁ]{1,4})|\d{2}[ \t]?(?-i:[А-ЯЁ]{2}))"
    r"[ \t\n]*(?:№|N(?=[ \t\d])|номер\w*)?[ \t\n]*\d{5,10})(?![\d\w])",
    re.IGNORECASE,
)

# Счет и код инвестора по подписи - в registry/labelled_values
MOEX_CODE_RE = re.compile(r"(?<!\w)[MМ][CС]\d{10}(?!\w)")


@dataclass(frozen=True)
class LabelledValueRe:
    """Значение по подписи из registry/labelled_values, собранное в регулярки."""
    name: str
    type: str
    # в тексте: подпись, разделитель, значение - в группе 1 или 2 (см. value_group)
    text: re.Pattern
    # в таблице: подпись и значение в соседних ячейках
    cell_label: re.Pattern
    cell_value: re.Pattern
    # ключ консистентности находки: одинаковый ключ - одна метка
    key: Callable[[str], str]


def _labelled_value(v) -> LabelledValueRe:
    value = rf"(?-i:{v.value})"
    if v.needs_sep:
        # ":", "=", тире; ключ и значение в кавычках: '"login": "ivanov_i"'
        text = (rf"(?<!\w)(?:{v.label})(?!\w)[\"']?[ \t]*(?:[:=]|[-–—](?=[ \t]))[ \t]*\n?[ \t]*"
                rf"[\"']?({value})"
                # подпись одна в строке, значение - вся следующая: "Логин\nivanov_i".
                rf"|(?<![^\n])[ \t]*(?:{v.label})[ \t]*\n[ \t]*({value})(?=[ \t]*(?:\n|$))")
    else:
        # "N" вместо "№" - только перед пробелом или цифрой: иначе это первая буква значения
        text = (rf"(?<!\w)(?:{v.label})(?!\w)[ \t]*(?:(?:[:=№]|N(?=[ \t\d]))[ \t]*)?\n?[ \t]*"
                rf"({value})")
    return LabelledValueRe(
        v.name, v.type,
        re.compile(text, re.IGNORECASE),
        re.compile(rf"^\s*(?:{v.label})\s*(?:№|N)?\s*[:=]?\s*$", re.IGNORECASE),
        re.compile(rf"^\s*{value}\s*$"),
        digits if v.digits_key else text_key,
    )


LABELLED_VALUES = tuple(_labelled_value(v) for v in VALUES)

def _money_after(label: str, amount: str) -> re.Pattern:
    """Сумма через несколько слов после подписи: "оклад в размере 120 000 руб.",
    "остаток на счете на 01.03.2024 составил 125 430,15". Между ними - без цифр, кроме
    даты и года, в пределах строки и колонки."""
    return re.compile(
        rf"(?<![\w/])(?:{label})(?![\w/])"
        rf"((?:[^\d\n%|]|{helpers.DATE}|(?:19|20)\d{{2}}[ \t]*г(?:од\w*|\.)){{1,60}}?)"
        rf"((?-i:{amount}))",
        re.IGNORECASE,
    )


# Доход со словами между подписью и суммой
INCOME_RE = _money_after(INCOME_LABEL, INCOME_AMOUNT)
# остаток по счету и задолженность по кредиту
BALANCE_RE = _money_after(BALANCE_LABEL, BALANCE_AMOUNT)

def value_group(m: re.Match) -> int:
    """Группа со значением: у подписи с разделителем два варианта записи, у остальных один."""
    return 1 if m.group(1) is not None else 2
