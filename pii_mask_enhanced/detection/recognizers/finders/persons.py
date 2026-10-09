"""Люди: ФИО, которые NER не берет (КАПСОМ, с инициалами), и дата рождения."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity
from .spans import Span, inside


def birth_dates(text: str) -> list[Entity]:
    return [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                   source=sources.BIRTH)
            for m in regs.BIRTH_DATE_RE.finditer(text)]


def persons(text: str) -> list[Entity]:
    out: list[Entity] = []
    named: list[Span] = []
    fio_words: set[str] = set()
    for rx in (regs.CAPS_FIO_RE, regs.INITIALS_RE):
        for m in rx.finditer(text):
            named.append(m.span())
            out.append(Entity("PERSON", m.group(), m.start(), m.end(),
                              " ".join(m.group().lower().split())))
            if rx is regs.CAPS_FIO_RE:
                fio_words.update(re.findall(r"[А-ЯЁ-]{4,}", m.group()))

    for m in regs.CAPS_PATR_RE.finditer(text):
        if not inside(m.start(), m.end(), named):
            out.append(Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower()))

    # одинокое слово капсом из уже найденного ФИО ("ВЕРШКОВА" на своей строке в PDF)
    known_fio = fio_words | set(helpers.prefixes(fio_words))
    for m in re.finditer(r"(?<![А-ЯЁA-Za-zа-яё-])[А-ЯЁ-]{4,}(?![А-ЯЁA-Za-zа-яё-])", text):
        if m.group() in known_fio and not inside(m.start(), m.end(), named):
            out.append(Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower()))
    return out
