"""Находка распознавателя и ключи консистентности: одинаковый ключ - одна метка."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Entity:
    type: str
    text: str
    start: int
    end: int
    key: str  # ключ консистентности: одинаковый key -> одна метка
    # слово не в именительном падеже ("Ивану")
    oblique: bool = False
    # кто нашел (registry/sources); решает спор при пересечениях
    source: str = ""


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def text_key(s: str) -> str:
    # "Республика  Беларусь" и "республика беларусь" - одно значение, одна метка
    return " ".join(s.lower().split())


def as_is(s: str) -> str:
    return s


def id_doc_key(value: str) -> str:
    # "АБ № 1234567", "АБ 1234567" и "АБ номер 1234567" - один документ, одна метка
    return re.sub(r"[Нн]омер|[\W_]", "", value).upper()


# символы, которыми скрывают цифры номера карты: "2200 00** **** 1234", "4276XXXXXXXX5679"
CARD_MASK_CHARS = "*•·Xx×"


def masked_card_key(value: str) -> str:
    # "4276 38** **** 5679" и "427638******5679" - одна карта, одна метка
    return "".join("*" if c in CARD_MASK_CHARS else c for c in value if c not in " -\t")


_LATIN_TO_CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")


def plate_key(value: str) -> str:
    # "A123BC77 RUS" латиницей и "А 123 ВС 77" - один номер, одна метка
    return re.sub(r"RUS|[\W_]", "", value.upper()).translate(_LATIN_TO_CYR)


def from_match(etype: str, m: re.Match, group: int = 0, key: Callable[[str], str] = text_key,
               source: str = "") -> Entity:
    """Находка из группы совпадения: текст, позиция и ключ - по одной группе."""
    value = m.group(group)
    return Entity(etype, value, m.start(group), m.end(group), key(value), source=source)
