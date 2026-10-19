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


def _masked_card_key(value: str) -> str:
    return "".join("*" if c in regs.CARD_MASK_CHARS else c for c in value if c not in " -\t")


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
            out.append(Entity("CARD", m.group(), m.start(), m.end(), _masked_card_key(m.group())))
            taken.append(m.span())
    for m in regs.CARD_LAST4_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        stars = sum(c in regs.CARD_MASK_CHARS for c in m.group(1))
        # "****5679" - карта и без подписи; "*5679" - сноска и код
        if stars >= 4 or _card_word_near(text, m.start(), m.end()):
            out.append(Entity("CARD", m.group(1), m.start(1), m.end(1), _masked_card_key(m.group(1))))
    for rx in (regs.CARD_BRAND_LAST4_RE, regs.CARD_ENDING_RE):
        for m in rx.finditer(text):
            g = 1 if m.group(1) else 2
            if rx is regs.CARD_BRAND_LAST4_RE or _card_word_near(text, m.start(), m.end()):
                out.append(Entity("CARD", m.group(g), m.start(g), m.end(g), "*" + m.group(g)))
    return out


def card_tracks(text: str) -> list[Entity]:
    out = []
    for rx in (regs.CARD_TRACK1_RE, regs.CARD_TRACK2_RE):
        for m in rx.finditer(text):
            pan = m.group(1) or m.group(2)
            if m.group(1) is None and not Validator.card_ok(pan):
                continue
            out.append(Entity("CARD", m.group(), m.start(), m.end(), pan))
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


_LATIN_TO_CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")


def plates(text: str) -> list[Entity]:
    """Госномер: легковой формат - всегда, прицеп, мотоцикл и такси - только у подписи."""
    out = []
    for rx in (regs.PLATE_RE, regs.PLATE_OTHER_RE):
        for m in rx.finditer(text):
            window = text[max(0, m.start() - 40):m.start()]
            labelled = regs.PLATE_LABEL_RE.search(window)
            # без подписи: буква слитно с цифрами ("В 100 км" - не номер) и рядом не товар
            if labelled or (rx is regs.PLATE_RE and not m.group()[1].isspace()
                            and not regs.VIN_GOODS_CTX_RE.search(window)):
                # "A123BC77 RUS" латиницей и "А 123 ВС 77" - один номер, одна метка
                key = re.sub(r"RUS|[\W_]", "", m.group().upper()).translate(_LATIN_TO_CYR)
                out.append(Entity("VEHICLE", m.group(), m.start(), m.end(), key,
                                  source=sources.REQUISITE if labelled else ""))
    return out


def _account_structure_ok(num: str) -> bool:
    return (bool(regs.ACCOUNT_BALANCE_RE.match(num))
            and num[5:8] in regs.ACCOUNT_CURRENCIES)


def accounts_bare(text: str) -> list[Entity]:
    """Счет без подписи: балансовый счет и валюта по плану счетов"""
    biks = None
    out = []
    for m in regs.ACCOUNT_BARE_RE.finditer(text):
        num = digits(m.group())
        ok = _account_structure_ok(num)
        if not ok:
            if biks is None:
                biks = {b.group() for b in regs.BIK_RU_RE.finditer(text)}
            ok = any(Validator.account_key_ok(num, b) for b in biks)
        if ok:
            # ключ - цифры: та же метка, что у счета с подписью "р/с"
            out.append(Entity("ACCOUNT", m.group(), m.start(), m.end(), num, source=sources.BARE))
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
    # "АБ № 1234567", "АБ 1234567" и "АБ номер 1234567" - один документ, одна метка
    return re.sub(r"[Нн]омер|[\W_]", "", value).upper()


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

    for m in regs.PASSPORT_SOLID_RE.finditer(text):
        if regs.PASSPORT_SOLID_LABEL_RE.search(text[max(0, m.start() - 60):m.start()]):
            out.append(Entity("PASSPORT", m.group(), m.start(), m.end(), m.group(),
                              source=sources.REQUISITE))
    return out
