"""Номера с контрольной суммой или узнаваемым форматом: карта, ИНН, СНИЛС, паспорт,
ОГРН, УИД, сертификат и документы из registry/id_documents."""
import re
from dataclasses import dataclass

from ...registry.id_documents import DOCS
from .. import helpers

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
# отдельным словом: число в артикуле ("OZN7701234567") может случайно пройти проверку
INN_RE = re.compile(r"(?<![\w])(?:\d{12}|\d{10})(?![\w])")
SNILS_RE = re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[ \-]?\d{2}(?!\d)")
# подпись прямо перед номером: с ней СНИЛС берем и с неверной суммой
SNILS_LABEL_RE = re.compile(r"снилс[ \t]*(?:№|:)?[ \t]*\n?[ \t]*$", re.IGNORECASE)
PASSPORT_RE = re.compile(
    r"(?<!\d)\d{2} ?\d{2}"
    # "№", "номер", запятая или пробел
    r"(?:[ \t]*,?[ \t]*(?:№|N|номер)[ \t]*|[ \t]*,?[ \t]+)"
    r"\d{6}(?!\d)",
    re.IGNORECASE,
)
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
