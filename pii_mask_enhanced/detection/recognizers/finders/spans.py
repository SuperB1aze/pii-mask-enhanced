"""Операции над спанами находок."""
from __future__ import annotations

import re

from ...registry import sources
from ..entity import Entity

Span = tuple[int, int]


def overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def inside(start: int, end: int, spans: list[Span]) -> bool:
    return any(s <= start and end <= e for s, e in spans)


def before(text: str, pos: int, width: int) -> str:
    # окно перед находкой: там ищется подпись ("ИНН", "паспорт", "VIN:")
    return text[max(0, pos - width):pos]


def line_window(text: str, start: int, end: int, width: int) -> Span:
    # окно вокруг находки
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    return max(line_start, start - width), min(line_end, end + width)


def outermost(matches: list[re.Match]) -> list[re.Match]:
    # совпадения, не вложенные строго в другое: оставляем самую полную находку
    spans = [m.span() for m in matches]
    return [m for m in matches
            if not any(s <= m.start() and m.end() <= e and (s, e) != m.span() for s, e in spans)]


def best_by_source(found: list[Entity]) -> list[Entity]:
    # дубли одного спана: оставляем находку с более надежным источником
    best: dict[tuple[str, int, int], Entity] = {}
    for ent in found:
        mark = (ent.type, ent.start, ent.end)
        if mark not in best or sources.rank(ent.source) > sources.rank(best[mark].source):
            best[mark] = ent
    return list(best.values())
