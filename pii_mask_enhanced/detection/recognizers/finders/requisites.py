"""Реквизиты по подписи, счета и номера документов."""
from __future__ import annotations

from ...registry import sources
from ...registry.entity_types import requisite_type
from .. import helpers
from .. import regulars as regs
from ..entity import Entity, as_is, from_match, id_doc_key


def docrefs(text: str) -> list[Entity]:
    out = []
    for m in regs.DOCREF_RE.finditer(text):
        num = m.group(2)
        if not any(ch.isdigit() for ch in num):
            continue
        # без "№" голое число - скорее сумма
        if not m.group(1) and num.isdigit():
            continue
        out.append(from_match("DOCREF", m, 2, key=str.lower, source=sources.DOCREF))
        if m.group(3):
            out.append(from_match("DATE", m, 3, key=as_is, source=sources.DOCREF))
    # "акт от 01.03.2024 № 15"
    for m in regs.DOCREF_DATE_FIRST_RE.finditer(text):
        if any(ch.isdigit() for ch in m.group(2)):
            out.append(from_match("DATE", m, 1, key=as_is, source=sources.DOCREF))
            out.append(from_match("DOCREF", m, 2, key=str.lower, source=sources.DOCREF))
    return out


def client_docnums(text: str) -> list[Entity]:
    # Номер с суффиксом типа клиента ("12345/ФЛ") - номер договора без подписи
    out = []
    for m in regs.DOC_SEGMENTS_RE.finditer(text):
        num = m.group()
        segments = regs.DOC_SEGMENT_SEP_RE.split(num)
        if not helpers.CLIENT_SUFFIXES & set(segments):
            continue
        if sum(c.isdigit() for c in num) < helpers.CLIENT_DOCNUM_MIN_DIGITS:
            continue
        out.append(from_match("DOCREF", m, key=_docnum_key, source=sources.DOCREF))
        out.append(from_match("REQ", m, key=_docnum_key))
    return out


def _docnum_key(value: str) -> str:
    # "12345 / ФЛ" и "12345/ФЛ" - один номер, одна метка
    return "".join(value.split()).lower()


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
    return [from_match(requisite_type(m.group(1), m.group(2)), m, 2, key=as_is,
                       source=sources.REQUISITE)
            for m in regs.REQUISITE_RE.finditer(text)]


def labelled_values(text: str) -> list[Entity]:
    """Значения из registry/labelled_values: счет, код инвестора, ЕСИА ID, логин, PIN, пол..."""
    return [from_match(lv.type, m, regs.value_group(m), key=lv.key, source=sources.REQUISITE)
            for lv in regs.LABELLED_VALUES for m in lv.text.finditer(text)]


def incomes(text: str) -> list[Entity]:
    """Сумма дохода, удержания, остатка по счету или долга через несколько слов после подписи."""
    return [from_match(etype, m, 2, source=sources.REQUISITE)
            for etype, rx in (("INCOME", regs.INCOME_RE), ("BALANCE", regs.BALANCE_RE))
            for m in rx.finditer(text)]


def moex_codes(text: str) -> list[Entity]:
    """Торговый код Мосбиржи "MC" + 10 цифр - единственный код инвестора без подписи."""
    return [from_match("INVESTOR", m) for m in regs.MOEX_CODE_RE.finditer(text)]


def gov_docs(text: str) -> list[Entity]:
    """"серия 77 № 007893219" - серия и номер одной меткой; паспорт и документы из
    registry/id_documents узнаются точнее и при пересечении побеждают по приоритету."""
    return [from_match("GOVDOC", m, 1, key=id_doc_key, source=sources.REQUISITE)
            for m in regs.GOVDOC_RE.finditer(text)]


def doc_numbers(text: str) -> list[Entity]:
    """Номера, отделенные от слова фразой: "Лицензия на ... №1326"."""
    return [from_match("REQ", m, g, key=as_is)
            for rx in regs.DOC_REQUISITE_RES for m in rx.finditer(text)
            for g in range(1, (m.lastindex or 0) + 1) if m.group(g)]
