"""Номера с контрольной суммой или узнаваемым форматом."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import (CARD_MASK_CHARS, Entity, as_is, digits, from_match, id_doc_key,
                      masked_card_key, plate_key)
from ..validators import Validator
from .spans import before, outermost


def cards(text: str) -> list[Entity]:
    out = []
    for m in regs.CARD_RE.finditer(text):
        d = digits(m.group())
        # с подписью "карта" номер с опечаткой в сумме - все равно карта
        labelled = (len(d) in regs.CARD_LENGTHS
                    and regs.CARD_LABEL_RE.search(before(text, m.start(), 40)))
        if labelled or Validator.card_ok(d):
            out.append(from_match("CARD", m, key=digits))
    return out


def _card_word_near(text: str, start: int, end: int) -> bool:
    return bool(regs.CARD_WORD_RE.search(text, max(0, start - 40), min(len(text), end + 20)))


def masked_cards(text: str) -> list[Entity]:
    """Номер карты, скрытый частично, и последние 4 цифры: по ним с остальными данными
    карту находят в выписке или переписке."""
    out = []
    taken = []
    for m in regs.CARD_MASKED_RE.finditer(text):
        compact = re.sub(r"[ -]", "", m.group())
        if 13 <= len(compact) <= 19 and regs.CARD_MASKED_FORM_RE.fullmatch(compact):
            out.append(from_match("CARD", m, key=masked_card_key))
            taken.append(m.span())
    for m in regs.CARD_LAST4_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        stars = sum(c in CARD_MASK_CHARS for c in m.group(1))
        # "****5679" - карта и без подписи; "*5679" - и сноска, и код
        if stars >= 4 or _card_word_near(text, m.start(), m.end()):
            out.append(from_match("CARD", m, 1, key=masked_card_key))
    for rx in (regs.CARD_BRAND_LAST4_RE, regs.CARD_ENDING_RE):
        for m in rx.finditer(text):
            if rx is regs.CARD_BRAND_LAST4_RE or _card_word_near(text, m.start(), m.end()):
                out.append(from_match("CARD", m, 1 if m.group(1) else 2, key=lambda v: "*" + v))
    return out


def card_tracks(text: str) -> list[Entity]:
    """Дорожка магнитной полосы - целиком; метка та же, что у номера карты в другом месте."""
    out = []
    for rx in (regs.CARD_TRACK1_RE, regs.CARD_TRACK2_RE):
        for m in rx.finditer(text):
            pan = m.group(1) or m.group(2)
            # без ";" и "%B" - только номер, прошедший проверку Луна
            if m.group(1) is None and not Validator.card_ok(pan):
                continue
            out.append(from_match("CARD", m, key=lambda _: pan))
    return out


def snils(text: str) -> list[Entity]:
    out = []
    for m in regs.SNILS_RE.finditer(text):
        if regs.SNILS_LABEL_RE.search(before(text, m.start(), 20)):
            # source=REQUISITE: подписанный номер скрывается и в других местах текста
            out.append(from_match("SNILS", m, key=digits, source=sources.REQUISITE))
        elif Validator.snils_ok(digits(m.group())):
            out.append(from_match("SNILS", m, key=digits))
    return out


def biks(text: str) -> list[Entity]:
    # без подписи "ИНН" - строгий режим ядра это учитывает
    return [from_match("BIK", m, key=as_is, source=sources.BARE)
            for m in regs.BIK_RU_RE.finditer(text)]


def vins(text: str) -> list[Entity]:
    out = []
    for m in regs.VIN_RE.finditer(text):
        vin = m.group()
        window = before(text, m.start(), 40)
        labelled = regs.VIN_LABEL_RE.search(window)
        # без подписи: буквы и цифры вместе, в конце - порядковый номер из 4 цифр, и рядом
        # не товар. Так отсекаются артикулы и коды товаров той же длины
        if labelled or (any(c.isalpha() for c in vin) and vin[-4:].isdigit()
                        and sum(c.isdigit() for c in vin) >= 6
                        and not regs.GOODS_CTX_RE.search(window)):
            out.append(from_match("VEHICLE", m, key=as_is,
                                  source=sources.REQUISITE if labelled else ""))
    return out


def plates(text: str) -> list[Entity]:
    """Госномер: легковой формат - всегда, прицеп, мотоцикл и такси - только у подписи."""
    out = []
    for rx in (regs.PLATE_RE, regs.PLATE_OTHER_RE):
        for m in rx.finditer(text):
            window = before(text, m.start(), 40)
            labelled = regs.PLATE_LABEL_RE.search(window)
            # без подписи: буква слитно с цифрами ("В 100 км" - не номер) и рядом не товар
            if labelled or (rx is regs.PLATE_RE and not m.group()[1].isspace()
                            and not regs.GOODS_CTX_RE.search(window)):
                out.append(from_match("VEHICLE", m, key=plate_key,
                                      source=sources.REQUISITE if labelled else ""))
    return out


def _account_structure_ok(num: str) -> bool:
    return (bool(regs.ACCOUNT_BALANCE_RE.match(num))
            and num[5:8] in regs.ACCOUNT_CURRENCIES)


def accounts_bare(text: str) -> list[Entity]:
    # Счет без подписи
    biks_in_text = None
    out = []
    for m in regs.ACCOUNT_BARE_RE.finditer(text):
        num = digits(m.group())
        ok = _account_structure_ok(num)
        if not ok:
            if biks_in_text is None:
                biks_in_text = {b.group() for b in regs.BIK_RU_RE.finditer(text)}
            ok = any(Validator.account_key_ok(num, b) for b in biks_in_text)
        if ok:
            # ключ - цифры: та же метка, что у счета с подписью "р/с"
            out.append(from_match("ACCOUNT", m, key=digits, source=sources.BARE))
    return out


def inns(text: str) -> list[Entity]:
    # без подписи "ИНН" - строгий режим ядра это учитывает
    return [from_match("INN", m, key=as_is, source=sources.BARE)
            for m in regs.INN_RE.finditer(text) if Validator.inn_ok(m.group())]


def certs(text: str) -> list[Entity]:
    return [from_match("CERT", m, key=str.lower) for m in regs.CERT_RE.finditer(text)
            if any(c.isdigit() for c in m.group()) and any(c.isalpha() for c in m.group())]


def ogrns(text: str) -> list[Entity]:
    return [from_match("OGRN", m, key=as_is)
            for m in regs.OGRN_RE.finditer(text) if Validator.ogrn_ok(m.group())]


def uids(text: str) -> list[Entity]:
    found = [m for rx in (regs.UID_RE, regs.UID_LOOSE_RE) for m in rx.finditer(text)
             if len(re.findall(r"[0-9a-f]", m.group(), re.IGNORECASE)) >= helpers.UID_MIN_HEX]
    return [from_match("UID", m, key=str.lower) for m in outermost(found)]


def kadastr_numbers(text: str) -> list[Entity]:
    return [from_match("KADASTR_NUMBER", m, key=as_is, source=sources.BARE)
            for m in regs.KADASTR_NUMBER_RE.finditer(text)]


def id_documents(text: str) -> list[Entity]:
    """Документы из registry/id_documents: номер формата документа рядом со словом документа."""
    out = []
    for doc in regs.ID_DOCS:
        # слово документа по всему тексту ищем, только когда нашелся номер его формата
        in_doc = None
        for m in doc.number.finditer(text):
            if in_doc is None:
                in_doc = doc.whole_doc and bool(doc.context.search(text))
            source = ""
            if doc.context is not None:
                window = before(text, m.start(), regs.ID_DOC_WINDOW)
                # слитный номер и слово с двойным смыслом только сразу за словом документа
                if m.group().isdigit() or doc.tight:
                    if not doc.label.search(window):
                        continue
                elif not (in_doc or doc.context.search(window)):
                    continue
                # номер, подписанный документом, скрывается и в других местах текста
                source = sources.REQUISITE
            out.append(from_match("IDDOC", m, key=id_doc_key, source=source))
    return out


def passports(text: str) -> list[Entity]:
    # "паспорт" в 40 знаках перед номером или где угодно в документе про паспорта
    whole_doc = bool(regs.PASSPORT_DOC_CTX_RE.search(text))
    out = []
    for m in regs.PASSPORT_RE.finditer(text):
        labelled = regs.PASSPORT_CTX_RE.search(before(text, m.start(), 40))
        if labelled or whole_doc:
            out.append(from_match("PASSPORT", m, key=digits,
                                  source=sources.REQUISITE if labelled else ""))
    # слитный номер - только сразу за словом паспорта, даже в документе про паспорта
    out += [from_match("PASSPORT", m, key=as_is, source=sources.REQUISITE)
            for m in regs.PASSPORT_SOLID_RE.finditer(text)
            if regs.PASSPORT_SOLID_LABEL_RE.search(before(text, m.start(), 60))]
    return out
