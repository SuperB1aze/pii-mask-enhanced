"""Адреса и место жительства."""
from __future__ import annotations

from ...registry import sources
from .. import regulars as regs
from ..entity import Entity
from .spans import outermost


def residences(text: str) -> list[Entity]:
    return [Entity("ADDRESS", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                   source=sources.RESIDENCE)
            for m in regs.RESIDENCE_RE.finditer(text)]


def addresses(text: str) -> list[Entity]:
    found = [m for rx in (regs.ADDRESS_RE, regs.ADDRESS_TAIL_RE, regs.ADDRESS_RUN_RE,
                          regs.ADDRESS_INDEX_RE)
             for m in rx.finditer(text)]
    return [Entity("ADDRESS", m.group(), m.start(), m.end(), " ".join(m.group().lower().split()))
            for m in outermost(found)]
