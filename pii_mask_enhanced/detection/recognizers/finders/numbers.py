"""Номера с контрольной суммой или узнаваемым форматом."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity, digits
from ..validators import Validator
from .spans import outermost


def cards(text: str) -> list[Entity]:
    out = []
    for m in regs.CARD_RE.finditer(text):
        d = digits(m.group())
        if len(d) == 16 and Validator.luhn_ok(d):
            out.append(Entity("CARD", m.group(), m.start(), m.end(), d))
    return out


def snils(text: str) -> list[Entity]:
    out = []
    for m in regs.SNILS_RE.finditer(text):
        d = digits(m.group())
        if Validator.snils_ok(d):
            out.append(Entity("SNILS", m.group(), m.start(), m.end(), d))
    return out


def inns(text: str) -> list[Entity]:
    # без подписи "ИНН" - строгий режим ядра это учитывает
    return [Entity("INN", m.group(), m.start(), m.end(), m.group(), source=sources.BARE)
            for m in regs.INN_RE.finditer(text) if Validator.inn_ok(m.group())]


def certs(text: str) -> list[Entity]:
    out = []
    for m in regs.CERT_RE.finditer(text):
        v = m.group()
        if any(c.isdigit() for c in v) and any(c.isalpha() for c in v):
            out.append(Entity("CERT", v, m.start(), m.end(), v.lower()))
    return out


def ogrns(text: str) -> list[Entity]:
    return [Entity("OGRN", m.group(), m.start(), m.end(), m.group())
            for m in regs.OGRN_RE.finditer(text) if Validator.ogrn_ok(m.group())]


def uids(text: str) -> list[Entity]:
    found = [m for rx in (regs.UID_RE, regs.UID_LOOSE_RE) for m in rx.finditer(text)
             if len(re.findall(r"[0-9a-f]", m.group(), re.IGNORECASE)) >= helpers.UID_MIN_HEX]
    return [Entity("UID", m.group(), m.start(), m.end(), m.group().lower())
            for m in outermost(found)]


def passports(text: str) -> list[Entity]:
    # "паспорт" в 40 знаках перед номером или где угодно в документе про паспорта
    whole_doc = bool(regs.PASSPORT_DOC_CTX_RE.search(text))
    out = []
    for m in regs.PASSPORT_RE.finditer(text):
        window = text[max(0, m.start() - 40):m.start()]
        if whole_doc or regs.PASSPORT_CTX_RE.search(window):
            out.append(Entity("PASSPORT", m.group(), m.start(), m.end(), digits(m.group())))
    return out
