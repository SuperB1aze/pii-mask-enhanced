"""Люди: ФИО, которые NER не берет (КАПСОМ, с инициалами), даты рождения и смерти."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity, as_is, from_match
from .spans import Span, inside


def birth_dates(text: str) -> list[Entity]:
    out = [from_match("DATE", m, 1, source=sources.BIRTH)
           for m in regs.BIRTH_DATE_RE.finditer(text)]
    for m in regs.BIRTH_YEAR_RE.finditer(text):
        out.append(from_match("DATE", m, 1 if m.group(1) else 2, key=as_is, source=sources.BIRTH))
    # дата и год смерти: тот же тип, что у даты рождения
    out += [from_match("DATE", m, 1, source=sources.DEATH)
            for rx in (regs.DEATH_DATE_RE, regs.DEATH_YEAR_RE) for m in rx.finditer(text)]
    return out


def persons(text: str) -> list[Entity]:
    out: list[Entity] = []
    named: list[Span] = []
    fio_words: set[str] = set()
    for rx in (regs.CAPS_FIO_RE, regs.INITIALS_RE):
        for m in rx.finditer(text):
            named.append(m.span())
            out.append(from_match("PERSON", m))
            if rx is regs.CAPS_FIO_RE:
                fio_words.update(re.findall(r"[А-ЯЁ-]{4,}", m.group()))

    for m in regs.CAPS_PATR_RE.finditer(text):
        if not inside(m.start(), m.end(), named):
            out.append(from_match("PERSON", m, key=str.lower))

    # одинокое слово капсом из уже найденного ФИО ("ВЕРШКОВА" на своей строке в PDF)
    known_fio = fio_words | set(helpers.prefixes(fio_words))
    for m in re.finditer(r"(?<![А-ЯЁA-Za-zа-яё-])[А-ЯЁ-]{4,}(?![А-ЯЁA-Za-zа-яё-])", text):
        if m.group() in known_fio and not inside(m.start(), m.end(), named):
            out.append(from_match("PERSON", m, key=str.lower))
    return out
