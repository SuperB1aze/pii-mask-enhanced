"""Адреса и место жительства."""
from __future__ import annotations

import re

from ...registry import sources
from .. import regulars as regs
from ..entity import Entity, as_is, from_match
from .spans import before, inside, outermost


def residences(text: str) -> list[Entity]:
    return [from_match("ADDRESS", m, 1, key=str.lower, source=sources.RESIDENCE)
            for m in regs.RESIDENCE_RE.finditer(text)]


def _regions(text: str) -> list[re.Match]:
    # "гражданство: Республика Беларусь" - страна гражданства, ее берет labelled_values
    return [m for m in regs.REGION_RE.finditer(text)
            if not regs.CITIZENSHIP_BEFORE_RE.search(before(text, m.start(), 30))]


def addresses(text: str) -> list[Entity]:
    found = [m for rx in (regs.ADDRESS_RE, regs.ADDRESS_TAIL_RE, regs.ADDRESS_RUN_RE,
                          regs.ADDRESS_INDEX_RE, regs.STREETLESS_RE)
             for m in rx.finditer(text)] + _regions(text)
    out = [from_match("ADDRESS", m) for m in outermost(found)]
    taken = [(e.start, e.end) for e in out]
    # Название после "г.", "пос.", "в городе": слово места остается в тексте.
    # Внутри полного адреса оно уже закрыто
    out += [from_match("ADDRESS", m, 1, key=str.lower)
            for m in regs.CITY_RE.finditer(text) if not inside(*m.span(1), taken)]
    return out


def _coord_labelled(text: str, start: int) -> bool:
    return bool(regs.COORD_LABEL_RE.search(before(text, start, 40)))


def coordinates(text: str) -> list[Entity]:
    out = []
    for m in regs.COORD_PAIR_RE.finditer(text):
        lat, lon = (float(m.group(i).replace("−", "-")) for i in (1, 3))
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        # без подписи "12.50, 13.75" - цены; у координат точность от 4 знаков
        precise = len(m.group(2)) >= 4 and len(m.group(4)) >= 4
        if precise or _coord_labelled(text, m.start()):
            out.append(from_match("ADDRESS", m, key=as_is))
    for m in regs.COORD_DEG_RE.finditer(text):
        # "25°" - температура или угол: нужна сторона света или подпись рядом
        if m.group(1) or m.group(2) or _coord_labelled(text, m.start()):
            value = m.group().rstrip()
            out.append(Entity("ADDRESS", value, m.start(), m.start() + len(value), value))
    return out
