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
        # с подписью "карта" номер с опечаткой в сумме - все равно карта
        labelled = (len(d) in regs.CARD_LENGTHS
                    and regs.CARD_LABEL_RE.search(text[max(0, m.start() - 40):m.start()]))
        if labelled or Validator.card_ok(d):
            out.append(Entity("CARD", m.group(), m.start(), m.end(), d))
    return out


def snils(text: str) -> list[Entity]:
    out = []
    for m in regs.SNILS_RE.finditer(text):
        d = digits(m.group())
        if regs.SNILS_LABEL_RE.search(text[max(0, m.start() - 20):m.start()]):
            # source=REQUISITE: подписанный номер скрывается и в других местах текста
            out.append(Entity("SNILS", m.group(), m.start(), m.end(), d,
                              source=sources.REQUISITE))
        elif Validator.snils_ok(d):
            out.append(Entity("SNILS", m.group(), m.start(), m.end(), d))
    return out


def biks(text: str) -> list[Entity]:
    # без подписи "ИНН" - строгий режим ядра это учитывает
    return [Entity("BIK", m.group(), m.start(), m.end(), m.group(), source=sources.BARE)
            for m in regs.BIK_RU_RE.finditer(text)]


def vins(text: str) -> list[Entity]:
    out = []
    for m in regs.VIN_RE.finditer(text):
        vin = m.group()
        window = text[max(0, m.start() - 40):m.start()]
        labelled = regs.VIN_LABEL_RE.search(window)
        # без подписи: буквы и цифры вместе, в конце - порядковый номер из 4 цифр, и рядом
        # не товар. Так отсекаются артикулы и коды товаров той же длины
        if labelled or (any(c.isalpha() for c in vin) and vin[-4:].isdigit()
                        and sum(c.isdigit() for c in vin) >= 6
                        and not regs.VIN_GOODS_CTX_RE.search(window)):
            out.append(Entity("VEHICLE", vin, m.start(), m.end(), vin,
                              source=sources.REQUISITE if labelled else ""))
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


def kadastr_numbers(text: str) -> list[Entity]:
    return [Entity("KADASTR_NUMBER", m.group(), m.start(), m.end(), m.group(), source=sources.BARE)
            for m in regs.KADASTR_NUMBER_RE.finditer(text)]


def dates(text: str) -> list[Entity]:
    return [Entity("DATE", m.group(), m.start(), m.end(), m.group(), source=sources.BARE)
            for m in regs.DATE_RE.finditer(text)]


def id_doc_key(value: str) -> str:
    # "АБ № 1234567" и "АБ 1234567" - один документ, одна метка
    return re.sub(r"[\W_]", "", value).upper()


def id_documents(text: str) -> list[Entity]:
    """Документы из registry/id_documents: номер формата документа рядом со словом документа."""
    out = []
    for doc in regs.ID_DOCS:
        # слово документа по всему тексту ищем, только когда нашелся номер его формата
        in_doc = None
        for m in doc.number.finditer(text):
            if in_doc is None:
                in_doc = doc.whole_doc and bool(doc.context.search(text))
            value = m.group()
            source = ""
            if doc.context is not None:
                window = text[max(0, m.start() - regs.ID_DOC_WINDOW):m.start()]
                # слитный номер и слово с двойным смыслом только сразу за словом документа
                if value.isdigit() or doc.tight:
                    if not doc.label.search(window):
                        continue
                elif not (in_doc or doc.context.search(window)):
                    continue
                # номер, подписанный документом, скрывается и в других местах текста
                source = sources.REQUISITE
            out.append(Entity("IDDOC", value, m.start(), m.end(), id_doc_key(value),
                              source=source))
    return out


def passports(text: str) -> list[Entity]:
    # "паспорт" в 40 знаках перед номером или где угодно в документе про паспорта
    whole_doc = bool(regs.PASSPORT_DOC_CTX_RE.search(text))
    out = []
    for m in regs.PASSPORT_RE.finditer(text):
        window = text[max(0, m.start() - 40):m.start()]
        if whole_doc or regs.PASSPORT_CTX_RE.search(window):
            out.append(Entity("PASSPORT", m.group(), m.start(), m.end(), digits(m.group())))
    return out
