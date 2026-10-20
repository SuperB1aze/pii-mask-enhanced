"""Номера с контрольной суммой или узнаваемым форматом: карта, ИНН, СНИЛС, паспорт,
ОГРН, УИД, сертификат и документы из registry/id_documents."""
import re
from dataclasses import dataclass

from ...registry.id_documents import DOCS
from .. import helpers
from ..entity import CARD_MASK_CHARS

# Номер не обрываем посередине, но продолжение - только группа от 3 цифр:
# срок "12/27" за картой номером не считается
CARD_RE = re.compile(
    r"(?<![\d-])(?<!\d )\d{4,8}(?:(?: {1,2}|-)\d{3,13}){1,4}(?!\d)(?!(?: {1,2}|-)\d{3})"
    r"|(?<!\d)\d{15,19}(?!\d)"
)
# подпись прямо перед номером, допускаем название системы: "карта Мир", "номер карты:"
CARD_LABEL_RE = re.compile(
    r"(?<!\w)(?:карт\w*|card)(?:[ \t]+[^\W\d_]+){0,2}[ \t]*(?:№|:)?[ \t]*$", re.IGNORECASE
)
CARD_LENGTHS = range(15, 20)
# Номер, скрытый частично: "2200 00** **** 1234", "4276XXXXXXXX5679", "**** **** **** 5679"
_MASK = f"[{re.escape(CARD_MASK_CHARS)}]"
_MASK_OR_DIGIT = rf"[\d{re.escape(CARD_MASK_CHARS)}]"
# граница номера: не буква, не цифра и не символ маски
_NOT_PAN = rf"[\w{re.escape(CARD_MASK_CHARS)}]"
CARD_MASKED_RE = re.compile(
    rf"(?<!{_NOT_PAN}){_MASK_OR_DIGIT}{{4}}(?:[ -]?{_MASK_OR_DIGIT}{{2,6}}){{2,4}}(?!{_NOT_PAN})")
CARD_MASKED_FORM_RE = re.compile(rf"(\d{{4}}|\d{{6}})?{_MASK}{{3,13}}\d{{4}}")
# Последние 4 цифры
CARD_LAST4_RE = re.compile(rf"(?<!{_NOT_PAN})({_MASK}{{1,12}}[ \t]?\d{{4}})(?!\d)")
CARD_BRAND_LAST4_RE = re.compile(
    r"(?<!\w)(?:MIR|Мир|МИР|Visa|VISA|MC|Mastercard|MasterCard|Maestro|UnionPay)"
    r"[ \t]?[-–*•·]+[ \t]?(\d{4})(?!\d)")
CARD_ENDING_RE = re.compile(
    r"(?:оканчивающ|заканчивающ)\w*[ \t]+на[ \t]+(\d{4})(?!\d)"
    r"|последни\w*[ \t]+(?:4|четыре)[ \t]+цифр\w*(?:[ \t]+номера)?(?:[ \t]+карт\w*)?[ \t:]*(\d{4})(?!\d)",
    re.IGNORECASE)
CARD_WORD_RE = re.compile(r"карт\w*|card|Visa|Mastercard|Maestro|\bМир\b|\bMIR\b", re.IGNORECASE)
# Магнитная полоса
CARD_TRACK1_RE = re.compile(r"%B(\d{12,19})\^[^^\n?]{2,26}\^\d{4}[^?\s]*\??")
CARD_TRACK2_RE = re.compile(r";(\d{12,19})=\d{4}[\d]*\??|(?<![\w=;])(\d{12,19})=\d{7,}\??(?![\w=])")
# отдельным словом: число в артикуле ("OZN7701234567") может случайно пройти проверку
INN_RE = re.compile(r"(?<![\w])(?:\d{12}|\d{10})(?![\w])")
# "112-233-445 95" и "112 233 445 95"
SNILS_RE = re.compile(r"(?<![\d-])\d{3}([ -])\d{3}\1\d{3}[ -]?\d{2}(?![\d-])")
BIK_RU_RE = re.compile(r"(?<![\w])04\d{7}(?![\w])")

# Счет без подписи
ACCOUNT_BARE_RE = re.compile(r"(?<![\w.-])(?<!\d )\d(?:[ .\-]?\d){19}(?!\d)(?![ .\-]?\d)")
# балансовый счет первого порядка
ACCOUNT_BALANCE_RE = re.compile(r"30[1-3]|40\d|4[1-5]\d|460|47\d")
# код валюты - цифры 6-8: рубль (810, 643), доллар, евро, юань, фунт, франк, иена, тенге,
# белорусский рубль, сум, сом, драм, лари, гонконгский доллар, лира, рупия, вона, гривна
ACCOUNT_CURRENCIES = frozenset({
    "810", "643", "840", "978", "156", "826", "756", "392", "398", "933", "860", "417",
    "051", "981", "344", "949", "356", "410", "980", "972", "944",
})
KADASTR_NUMBER_RE = re.compile(r"(?<![\d:])\d{2}:\d{2}:\d{6,9}:\d+(?![\d:])")
# подпись прямо перед номером: с ней СНИЛС берем и с неверной суммой
SNILS_LABEL_RE = re.compile(r"снилс[ \t]*(?:№|:)?[ \t]*\n?[ \t]*$", re.IGNORECASE)
PASSPORT_RE = re.compile(
    r"(?<!\d)\d{2} ?\d{2}"
    # "№", "номер", запятая, пробел или дефис
    r"(?:[ \t]*,?[ \t]*(?:№|N|номер)[ \t]*|[ \t]*,?[ \t]+|-)"
    r"\d{6}(?!\d)",
    re.IGNORECASE,
)

# "паспорт 4510123456", "паспорт гражданина РФ 4510123456", "ДУЛ: 4510123456"
PASSPORT_SOLID_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
PASSPORT_SOLID_LABEL_RE = re.compile(
    r"(?:паспорт\w*(?:[ \t]+гражданин\w*)?(?:[ \t]+(?:РФ|России|Российской[ \t]+Федерации))?"
    r"|(?<!\w)ДУЛ|серия[ \t]+и[ \t]+номер(?:[ \t]+паспорта)?)"
    r"[ \t]*(?:[:№]|N(?=[ \t\d]))?[ \t]*$",
    re.IGNORECASE)
PASSPORT_CTX_RE = re.compile(r"паспорт\w*|сери[ия]\w*", re.IGNORECASE)
# документ про паспорта - номера ищем по всему тексту, а не рядом со словом
PASSPORT_DOC_CTX_RE = re.compile(
    r"\bДУЛ\b|паспорт\w*|удостоверяющ\w+\s+личность", re.IGNORECASE
)


@dataclass(frozen=True)
class IdDocRe:
    """Документ из registry/id_documents, собранный в регулярки."""
    name: str
    number: re.Pattern
    context: re.Pattern | None
    # слово документа прямо перед номером, через ":", "№", "серия", "номер"
    label: re.Pattern | None
    whole_doc: bool
    tight: bool


ID_DOCS = tuple(
    IdDocRe(d.name, re.compile(rf"(?<![\w№-])(?:{d.number})(?!\w)"),
            re.compile(d.context, re.IGNORECASE) if d.context else None,
            re.compile(rf"(?:{d.context})(?:[ \t:№,]|сери[яи]|номер)*$", re.IGNORECASE)
            if d.context else None,
            d.whole_doc, d.tight)
    for d in DOCS
)
# слово документа перед номером: "военный билет: серия АБ № 1234567"
ID_DOC_WINDOW = 60

# ОГРН (13) и ОГРНИП (15)
OGRN_RE = re.compile(r"(?<!\d)(?:\d{15}|\d{13})(?!\d)")
# последняя группа необязательна: хвост в PDF уезжает, а головы хватает
UID_RE = re.compile(
    rf"(?<![\w-])[0-9a-f]{{8}}(?:-{helpers.WRAP}[0-9a-f]{{4}}){{1,3}}"
    rf"(?:-{helpers.WRAP}[0-9a-f]{{12}}(?:-\d{{1,3}})?)?-?(?![\w])",
    re.IGNORECASE,
)
# УИД с потерянными дефисами; меньше 16 hex-знаков - не УИД
UID_LOOSE_RE = re.compile(r"(?<![\w-])[0-9a-f]{8}-[0-9a-f-]{8,48}(?![\w])", re.IGNORECASE)

# серийный номер сертификата ЭП
CERT_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{16,64}(?![0-9A-Za-z])")

# VIN: 17 знаков без I, O и Q - их не используют, чтобы не путать с 1 и 0
VIN_RE = re.compile(r"(?<![0-9A-Za-z])[A-HJ-NPR-Z0-9]{17}(?![0-9A-Za-z])")
# подпись прямо перед номером: "VIN:", "номер кузова", "идентификационный номер (VIN)"
VIN_LABEL_RE = re.compile(
    r"(?<!\w)(?:VIN|вин[ -]?код|номер[ \t]+кузова|идентификационн\w*[ \t]+номер\w*)"
    r"(?:[ \t]*\(VIN\))?[ \t]*(?:№|:)?[ \t]*$", re.IGNORECASE)
# Госномер: только 12 букв, похожих на латиницу; их и набирают латиницей
_PLATE_L = r"[АВЕКМНОРСТУХABEKMHOPCTYX]"
# регион: 2 цифры или 3 с первой ненулевой; "RUS" бывает
_PLATE_REGION = r"[ \t]?(?:\d{2}|[1-9]\d{2})(?:[ \t]?(?:RUS|rus))?"
# легковой "А123ВС77" - узнается и без подписи
PLATE_RE = re.compile(
    rf"(?<![\w-]){_PLATE_L}[ \t]?\d{{3}}[ \t]?{_PLATE_L}{{2}}{_PLATE_REGION}(?![\w-])")
# Без подписи - любой код: прицеп "АВ 1234 77", мотоцикл и военный "1234 АВ 77",
# такси "АВ 123 77", транзитный "АВ 123 С 77", полицейский "А 1234 77",
# дипломатический "001 CD 1 77", "123 D 456 77"
PLATE_OTHER_RE = re.compile(
    rf"(?<![\w-])(?:{_PLATE_L}{{2}}[ \t]?\d{{3}}[ \t]?{_PLATE_L}"
    rf"|{_PLATE_L}{{1,2}}[ \t]?\d{{4}}|{_PLATE_L}{{2}}[ \t]?\d{{3}}|\d{{4}}[ \t]?{_PLATE_L}{{2}}"
    r"|\d{3}[ \t]?(?:CD[ \t]?\d|[DT][ \t]?\d{3}))"
    rf"{_PLATE_REGION}(?![\w-])")
# подпись прямо перед номером: "госномер", "гос. рег. знак", "г/н", "ГРЗ", "номер автомобиля"
PLATE_LABEL_RE = re.compile(
    r"(?<!\w)(?:гос(?:ударственн\w*|\.)?[ \t]*(?:рег(?:истрационн\w*|\.)?[ \t]*)?(?:номер|знак)\w*"
    r"|г/н|г\.[ \t]?н\.|(?-i:ГРЗ)"
    r"|(?:транзитн|дипломатическ|военн|полицейск)\w*[ \t]+(?:(?:гос|рег)\w*\.?[ \t]+)?(?:номер|знак)\w*"
    r"|регистрационн\w*[ \t]+(?:номер|знак)\w*"
    r"|номер\w*[ \t]+(?:(?-i:ТС)|автомобил\w*|машин\w*|транспортн\w*[ \t]+средств\w*))"
    r"(?:[ \t]+(?:(?-i:ТС)|автомобил\w*|транспортн\w*[ \t]+средств\w*))?"
    r"[ \t]*(?:№|:)?[ \t]*$", re.IGNORECASE)

# артикул товара
GOODS_CTX_RE = re.compile(r"артикул\w*|арт\.|код\w*[ \t]+товар\w*|SKU|номенклатур\w*",
                          re.IGNORECASE)
