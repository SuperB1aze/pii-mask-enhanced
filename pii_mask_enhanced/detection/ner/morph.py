"""Словарная морфология (pymorphy через natasha): один словарь на весь процесс."""
from __future__ import annotations

import warnings
from functools import cache
from typing import TYPE_CHECKING, cast

from . import helpers

if TYPE_CHECKING:
    from natasha import MorphVocab
    from natasha.morph.vocab import MorphForm

# pymorphy2 (зависимость natasha) импортирует pkg_resources, setuptools<81 об этом предупреждает
warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)

# имя или название, вошедшее в словарь: такое слово нарицательным не считаем
_PROPER = helpers.NAME_GRAMMEMES | {"Orgn"}


@cache
def vocab() -> MorphVocab:
    from natasha import MorphVocab

    return MorphVocab()


def parse(word: str) -> list[MorphForm]:
    # MorphVocab всегда отдает MorphForm, но pymorphy2 без аннотаций и Pylance видит tuple
    return cast("list[MorphForm]", vocab().parse(word))


def known(word: str) -> list[MorphForm]:
    return [p for p in parse(word) if p.is_known]


def has_name(parses: list[MorphForm]) -> bool:
    """Есть ли разбор как имя, фамилия или отчество."""
    return any(g in helpers.NAME_GRAMMEMES for p in parses for g in p.tag.grammemes)


def is_geography(word: str) -> bool:
    parses = known(word.capitalize())
    return bool(parses) and all("Geox" in p.tag.grammemes for p in parses)


def is_known_common(word: str) -> bool:
    """Словарь знает слово только как нарицательное: "РЕШЕНИЕ", "Проекты"."""
    parses = known(word.capitalize())
    return bool(parses) and not any(g in _PROPER for p in parses for g in p.tag.grammemes)


def looks_like_person(text: str) -> bool:
    # похож ли спан на ФИО живого человека, а не на марку товара
    return any(has_name(known(token)) for token in text.split())


def is_stop_term(text: str) -> bool:
    # родовой термин
    term = " ".join(text.lower().split()).strip(" -–,.:;()[]\"'«»")
    if not term:
        return True
    if term in helpers.STOP_TERMS:
        return True
    head = helpers.TERM_TAIL.sub("", term).strip()
    return bool(head) and head != term and head in helpers.STOP_TERMS
