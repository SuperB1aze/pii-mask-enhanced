"""Словарная морфология (pymorphy через natasha): один словарь на весь процесс."""
from __future__ import annotations

import re
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


def surname_nominative(word: str, female: bool) -> str:
    """Фамилия в именительном падеже того же рода: "Белоусовой" -> "белоусова".
    Несклоняемая или незнакомая словарю ("Черных") остается как есть."""
    gender = "femn" if female else "masc"
    for p in parse(word):
        if "Surn" in p.tag.grammemes and gender in p.tag.grammemes:
            form = p.inflect({"Nom"})
            if form:
                return form.word
    return word.lower()


def surname_forms(word: str) -> set[str]:
    """Именительные формы фамилии обоих родов: одиночная "Сухаревой" - это "сухарева"."""
    return {word.lower(), surname_nominative(word, True), surname_nominative(word, False)}


def surname_lexeme(word: str) -> set[str]:
    """Все падежные формы фамилии обоих родов; не фамилия по словарю - само слово."""
    forms = {f.word for p in parse(word) if "Surn" in p.tag.grammemes for f in p.lexeme}
    return forms | {word.lower()}


def is_name_part(word: str) -> bool:
    # имя или отчество по словарю
    return any(g in {"Name", "Patr"} for p in parse(word) for g in p.tag.grammemes)


def is_female_patronymic(text: str) -> bool:
    # отчество в спане женское: "Сергеевны", "Петровна"
    return any("Patr" in p.tag.grammemes and "femn" in p.tag.grammemes
               for word in text.split() for p in parse(word.strip(".,")))


def looks_like_person(text: str) -> bool:
    # похож ли спан на ФИО живого человека, а не на марку товара
    return any(has_name(known(token)) for token in text.split())


def _normal(word: str) -> str:
    parses = parse(word)
    return parses[0].normal if parses else word.lower()


def is_party_role(text: str) -> bool:
    # роль стороны договора в любом падеже: «Заказчик», «Исполнителя»
    words = text.strip(" «»\"'").split()
    return len(words) == 1 and _normal(words[0]) in helpers.PARTY_ROLES


def is_generic_unit(text: str) -> bool:
    """Подразделение без собственного названия: "Финансовый отдел", "Отдел кадров".
    Кавычки, цифры, латиница, имя собственное или заглавные буквы дальше первого слова -
    уже название: "Отдел «Север»", "Ромашка Групп"."""
    text = text.strip()
    if not re.fullmatch(r"[А-ЯЁа-яё -]+", text):
        return False
    words = text.split()
    return (all(w.islower() for w in words[1:])
            and any(_normal(w) in helpers.UNIT_NOUNS for w in words)
            and all(is_known_common(w) for w in words))


def is_stop_term(text: str) -> bool:
    # родовой термин
    term = " ".join(text.lower().split()).strip(" -–,.:;()[]\"'«»")
    if not term:
        return True
    if term in helpers.STOP_TERMS:
        return True
    head = helpers.TERM_TAIL.sub("", term).strip()
    return bool(head) and head != term and head in helpers.STOP_TERMS
