"""Люди: ФИО, которые NER не берет (КАПСОМ, с инициалами), и дата рождения."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity
from .spans import Span, inside


def birth_dates(text: str) -> list[Entity]:
    out = [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                  source=sources.BIRTH)
           for m in regs.BIRTH_DATE_RE.finditer(text)]
    for m in regs.BIRTH_YEAR_RE.finditer(text):
        g = 1 if m.group(1) else 2
        out.append(Entity("DATE", m.group(g), m.start(g), m.end(g), m.group(g),
                          source=sources.BIRTH))
    # дата и год смерти
    for rx in (regs.DEATH_DATE_RE, regs.DEATH_YEAR_RE):
        out += [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                       source=sources.DEATH)
                for m in rx.finditer(text)]
    return out


def criminal(text: str) -> list[Entity]:
    # судимость
    out = [Entity("PERSONAL", m.group(), m.start(), m.end(), " ".join(m.group().lower().split()))
           for m in regs.CRIMINAL_STATUS_RE.finditer(text)]
    for m in regs.CRIMINAL_ARTICLE_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end < 0 else line_end
        lo = max(line_start, m.start() - regs.CRIMINAL_WINDOW)
        hi = min(line_end, m.end() + regs.CRIMINAL_WINDOW)
        if regs.CRIMINAL_TRIGGER_RE.search(text, lo, hi):
            out.append(Entity("PERSONAL", m.group(), m.start(), m.end(),
                              " ".join(m.group().lower().split())))
    return out


def health(text: str) -> list[Entity]:
    out = [Entity("PERSONAL", m.group(1), m.start(1), m.end(1), m.group(1).upper())
           for m in regs.ICD_RE.finditer(text)]
    out += [Entity("PERSONAL", m.group(), m.start(), m.end(), " ".join(m.group().lower().split()))
            for m in regs.DISABILITY_RE.finditer(text)]
    return out


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
