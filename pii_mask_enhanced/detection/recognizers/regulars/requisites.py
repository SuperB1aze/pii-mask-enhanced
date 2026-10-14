"""Реквизиты по подписи, номера документов и значения из registry/labelled_values."""
import re
from dataclasses import dataclass
from typing import Callable

from ...registry.entity_types import REQUISITE_WORD
from ...registry.labelled_values import VALUES
from .. import helpers
from ..entity import digits, text_key

# Число рядом с подписью, без контрольной суммы. Пары "ИНН/КПП" - в PAIRED_REQUISITE_RE.
REQUISITE_RE = re.compile(
    rf"(?<![/\w])({REQUISITE_WORD}"
    r"|рег(?:истрационный)?\.?[ \t]*(?:номер|№))"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{3,15})(?![ \t]*/[ \t]*\d)",
    re.IGNORECASE,
)

# "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку
PAIRED_REQUISITE_RE = re.compile(
    rf"({REQUISITE_WORD}(?:[ \t]*(?:/|и)[ \t]*{REQUISITE_WORD})+)"
    rf"[^\d\n]{{0,80}}?"
    rf"(\d{{3,15}}(?:[ \t]*/[ \t]*\d{{0,15}})+)",
    re.IGNORECASE,
)

# "от 01.09.2026" за номером, найденным не через DOCREF_RE
DATE_AFTER_RE = re.compile(rf"[ \t]{{0,3}}от[ \t]{{0,3}}({helpers.DATE})", re.IGNORECASE)

DOCREF_RE = re.compile(
    rf"{helpers.DOC_ANCHOR}{helpers.DOC_GAP}"
    r"[ \t]{0,3}(№|N|N°)?[ \t]{0,3}"
    r"(?<![\w-])([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/._]{1,30})"
    rf"(?:[ \t]{{1,3}}от[ \t]{{1,3}}({helpers.DATE}))?",
    re.IGNORECASE,
)

# Номер из сегментов через "/" или "-": "12345/ФЛ", "ФЛ-12345", "625/0000-0123456 / ЮЛ"
DOC_SEGMENTS_RE = re.compile(
    r"(?<![\w./-])\w+(?:\.\w+)*(?:(?:-|[ \t]?/[ \t]?)\w+(?:\.\w+)*)+(?![\w/-])"
)
DOC_SEGMENT_SEP_RE = re.compile(r"[ \t]?[/-][ \t]?")

# номера, отделенные от слова фразой: "Лицензия на ... №1326"
DOC_REQUISITE_RES = (
    # "серия 77 № 007893219"
    re.compile(r"сери[яи][ \t\n]*(\d{2,4})[ \t\n]*№?[ \t\n]*(\d{5,9})", re.IGNORECASE),
    re.compile(r"(?:договор\w*|(?<!\w)ДБО)[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"соглашени\w*[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"(?:лицензи\w+|свидетельств\w+)[^№]{0,120}№[ \t]*(\d[\d-]{2,20})", re.IGNORECASE),
    re.compile(r"регистрационный[ \t\n]+номер[^:]{0,90}:[ \t\n]*(\d{3,15})", re.IGNORECASE),
)

# Счет и код инвестора по подписи - в registry/labelled_values.
# Торговый код фондового рынка Мосбиржи узнается и без подписи; М и С бывают кириллицей
MOEX_CODE_RE = re.compile(r"(?<!\w)[MМ][CС]\d{10}(?!\w)")


@dataclass(frozen=True)
class LabelledValueRe:
    """Значение по подписи из registry/labelled_values, собранное в регулярки."""
    name: str
    type: str
    # в тексте: подпись, разделитель, значение (группа 1)
    text: re.Pattern
    # в таблице: подпись и значение в соседних ячейках
    cell_label: re.Pattern
    cell_value: re.Pattern
    # ключ консистентности находки: одинаковый ключ - одна метка
    key: Callable[[str], str]


def _labelled_value(v) -> LabelledValueRe:
    # "N" вместо "№" - только перед пробелом или цифрой: иначе это первая буква значения
    sep = r"[ \t]*[:=][ \t]*" if v.needs_sep else r"[ \t]*(?:(?:[:=№]|N(?=[ \t\d]))[ \t]*)?"
    value = rf"(?-i:{v.value})"
    return LabelledValueRe(
        v.name, v.type,
        re.compile(rf"(?<!\w)(?:{v.label})(?!\w){sep}\n?[ \t]*({value})", re.IGNORECASE),
        re.compile(rf"^\s*(?:{v.label})\s*(?:№|N)?\s*[:=]?\s*$", re.IGNORECASE),
        re.compile(rf"^\s*{value}\s*$"),
        digits if v.digits_key else text_key,
    )


LABELLED_VALUES = tuple(_labelled_value(v) for v in VALUES)
