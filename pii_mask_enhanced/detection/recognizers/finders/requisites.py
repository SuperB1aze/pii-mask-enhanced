"""Реквизиты по подписи, счета и номера документов."""
from __future__ import annotations

from ...registry import sources
from ...registry.entity_types import requisite_type
from .. import helpers
from .. import regulars as regs
from ..entity import Entity


def docrefs(text: str) -> list[Entity]:
    out = []
    for m in regs.DOCREF_RE.finditer(text):
        num = m.group(2)
        if not any(ch.isdigit() for ch in num):
            continue
        # без "№" голое число - скорее сумма
        if not m.group(1) and num.isdigit():
            continue
        out.append(Entity("DOCREF", num, m.start(2), m.end(2), num.lower(),
                          source=sources.DOCREF))
        if m.group(3):
            out.append(Entity("DATE", m.group(3), m.start(3), m.end(3), m.group(3),
                              source=sources.DOCREF))
    return out


def paired(text: str) -> list[Entity]:
    """Пары "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку."""
    out = []
    for m in regs.PAIRED_REQUISITE_RE.finditer(text):
        labels = helpers.SPLIT_LABELS.split(m.group(1))
        nums = helpers.SPLIT_NUMS.split(m.group(2))
        if len(labels) != len(nums):
            continue        # не угадываем, где ИНН, а где КПП
        pos = m.start(2)
        for label, num in zip(labels, nums):
            if not num:
                continue    # у ИП нет КПП
            start = text.index(num, pos)
            out.append(Entity(requisite_type(label, num), num, start, start + len(num), num,
                              source=sources.REQUISITE))
            pos = start + len(num)
    return out


def labelled(text: str) -> list[Entity]:
    return [Entity(requisite_type(m.group(1), m.group(2)), m.group(2), m.start(2), m.end(2),
                   m.group(2), source=sources.REQUISITE)
            for m in regs.REQUISITE_RE.finditer(text)]


def accounts(text: str) -> list[Entity]:
    return [Entity("ACCOUNT", m.group(2), m.start(2), m.end(2), m.group(2),
                   source=sources.REQUISITE)
            for m in regs.ACCOUNT_RE.finditer(text)]


def doc_numbers(text: str) -> list[Entity]:
    """Номера, отделенные от слова фразой: "Лицензия на ... №1326"."""
    return [Entity("REQ", m.group(g), m.start(g), m.end(g), m.group(g))
            for rx in regs.DOC_REQUISITE_RES for m in rx.finditer(text)
            for g in range(1, (m.lastindex or 0) + 1) if m.group(g)]
