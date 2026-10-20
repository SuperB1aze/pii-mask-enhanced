"""Специальные категории (ст. 10 152-ФЗ) и сведения рядом с ними: судимость, здоровье,
допуск к гостайне и классный чин, доля в капитале."""
from __future__ import annotations

import re

from .. import regulars as regs
from ..entity import Entity, from_match
from .spans import line_window


def criminal(text: str) -> list[Entity]:
    """Судимость: статья кодекса при слове о преследовании в той же строке и обороты
    "ранее судим", "судимость погашена"."""
    out = [from_match("PERSONAL", m) for m in regs.CRIMINAL_STATUS_RE.finditer(text)]
    for m in regs.CRIMINAL_ARTICLE_RE.finditer(text):
        lo, hi = line_window(text, m.start(), m.end(), regs.CRIMINAL_WINDOW)
        if regs.CRIMINAL_TRIGGER_RE.search(text, lo, hi):
            out.append(from_match("PERSONAL", m))
    return out


def health(text: str) -> list[Entity]:
    """Здоровье: код МКБ-10 после "диагноз", "Ds", "код МКБ" и обороты об инвалидности."""
    return ([from_match("PERSONAL", m, 1, key=str.upper) for m in regs.ICD_RE.finditer(text)]
            + [from_match("PERSONAL", m) for m in regs.DISABILITY_RE.finditer(text)])


def clearance(text: str) -> list[Entity]:
    """Допуск к гостайне и классный чин гражданской службы - оборот целиком.
    "Допуск к гостайне: имеется" - подпись поля, ее значение берет labelled_values."""
    return [from_match("PERSONAL", m) for m in regs.CLEARANCE_RE.finditer(text)
            if not re.match(r"[ \t]*:", text[m.end():])]


def shares(text: str) -> list[Entity]:
    """Доля в капитале или в праве собственности - процент или дробь после подписи."""
    return [from_match("PERSONAL", m, 1)
            for rx in (regs.SHARE_RE, regs.SHARE_OWN_RE) for m in rx.finditer(text)]
