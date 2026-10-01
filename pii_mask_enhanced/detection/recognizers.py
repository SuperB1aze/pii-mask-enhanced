"""Форматные ПД РФ: regex + контрольные суммы."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Entity:
    type: str
    text: str
    start: int
    end: int
    key: str  # ключ консистентности: одинаковый key -> одна метка
    # слово не в именительном падеже ("Ивану")
    oblique: bool = False
    # "dict", "requisite", "bare" и др. - кто нашел; решает спор при пересечениях
    source: str = ""


# Наши собственные фейки не должны маскироваться повторно
FAKE_PHONE_CODE = "000"
FAKE_EMAIL_RE = re.compile(r"^user\d+@example\.com$", re.IGNORECASE)

PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[ \-]?\(?\d{3}\)?[ \-]?\d{3}[ \-]?\d{2}[ \-]?\d{2}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TG_RE = re.compile(r"(?<![\w.\-@])@[A-Za-z][A-Za-z0-9_]{4,31}\b")
CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[ \-]?){3}\d{4}(?!\d)")
# отдельным словом: число в артикуле ("OZN7701234567") может случайно пройти проверку
INN_RE = re.compile(r"(?<![\w])(?:\d{12}|\d{10})(?![\w])")
SNILS_RE = re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[ \-]?\d{2}(?!\d)")
PASSPORT_RE = re.compile(r"(?<!\d)\d{4} \d{6}(?!\d)")
PASSPORT_CTX_RE = re.compile(r"паспорт\w*|сери[ия]\w*", re.IGNORECASE)
# документ про паспорта - номера ищем по всему тексту, а не рядом со словом
PASSPORT_DOC_CTX_RE = re.compile(
    r"\bДУЛ\b|паспорт\w*|удостоверяющ\w+\s+личность", re.IGNORECASE
)
# ОГРН (13) и ОГРНИП (15)
OGRN_RE = re.compile(r"(?<!\d)(?:\d{15}|\d{13})(?!\d)")
# УИД договора (758-П). В PDF он рвется по дефису - допускаем один перенос строки.
_WRAP = r"[ \t]*\n?[ \t]*"
# последняя группа необязательна: хвост в PDF уезжает, а головы хватает
UID_RE = re.compile(
    rf"(?<![\w-])[0-9a-f]{{8}}(?:-{_WRAP}[0-9a-f]{{4}}){{1,3}}"
    rf"(?:-{_WRAP}[0-9a-f]{{12}}(?:-\d{{1,3}})?)?-?(?![\w])",
    re.IGNORECASE,
)
# УИД с потерянными дефисами; меньше 16 hex-знаков - не УИД
UID_LOOSE_RE = re.compile(r"(?<![\w-])[0-9a-f]{8}-[0-9a-f-]{8,48}(?![\w])", re.IGNORECASE)
_UID_MIN_HEX = 16

# Организации
_ORG_FORM = (
    r"(?:АО|ОАО|ЗАО|ПАО|НАО|ООО|НКО|АНО|ПК|ГК|ФГУП|МУП|ИП"
    r"|Акционерное\s+общество|Публичное\s+акционерное\s+общество"
    r"|Общество\s+с\s+ограниченной\s+ответственностью"
    r"|Банк|Компания|Бюро|Фонд)"
)
# для проверки находок NER (Masker.ner_org_needs_form)
ORG_FORM_RE = re.compile(rf"\b{_ORG_FORM}\b", re.IGNORECASE)

ORG_QUOTED_RE = re.compile(
    rf"{_ORG_FORM}[ \t]*\n?[ \t]*[«\"][^»\"]{{2,80}}[»\"]", re.IGNORECASE
)

# родовое слово + название в кавычках: 'ТРЦ "Ромашка"', 'БЦ "Полевой"'
_ORG_TYPE_GENERIC = (
    r"(?:ТРЦ|ТЦ|БЦ|ЖК|МФК|ТПУ|СРО|НИИ|КБ|завод|комбинат|фабрика|агентство"
    r"|холдинг|группа|управление|департамент)"
)
ORG_GENERIC_QUOTED_RE = re.compile(
    rf"(?<![\w-]){_ORG_TYPE_GENERIC}[ \t]+([«\"][^»\"\n]{{2,80}}[»\"])", re.IGNORECASE
)

# "Zaprosto", "Кураж+": до трех слов с заглавной, чтобы не брать цитаты
ORG_QUOTED_NAME_RE = re.compile(
    r"[«\"“]((?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)(?:[ \t](?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)){0,2})[»\"”]")

# форма после названия: "Василек Технологии, ЗАО" (hh.ru); без ИП, "банк", "фонд"
_ORG_FORM_TRAILING = r"(?:АО|ОАО|ЗАО|ПАО|НАО|ООО|НКО|АНО|ФГУП|ГУП|МУП|ФГБУ)"
# в "Москва, ООО Ромашка" форма относится к следующему названию - хвост это отсекает
ORG_TRAILING_FORM_RE = re.compile(
    r"(?<![\w-])(?:[А-ЯЁA-Z][\w-]*[ \t]+){0,2}[А-ЯЁA-Z][\w-]*"
    rf"[ \t]*,[ \t]*{_ORG_FORM_TRAILING}(?![\w-])(?![ \t]+[«\"А-ЯЁA-Z])"
)

# общие слова названий - по документу их не ищем
_ORG_GENERIC = frozenset({
    "банк", "банка", "банку", "бюро", "общество", "компания", "группа", "фонд",
    "кредитных", "историй", "кредитной", "истории", "объединенное", "национальное",
    "коммерческий", "акционерное", "публичное", "российской", "федерации",
    "сервис", "сервисы", "центр", "холдинг", "корпорация", "страховая",
})


def _prefixes(words, minlen: int = 6) -> dict[str, str]:
    """Обрезки слов -> полное слово: PDF режет текст по колонке ("КОНСТАНТИНОВИ")."""
    out: dict[str, str] = {}
    for w in words:
        for n in range(minlen, len(w)):
            out.setdefault(w[:n], w)
    return out


# подчеркивание - разделитель слов: "Эквифакс_уникальные_заявки"
_WORD_CHAR = r"[^\W_]|-"


def _org_stems(name: str) -> list[str]:
    """Отличительные слова названия."""
    words = re.findall(r"[А-ЯЁA-Z][\w-]{2,}", name)
    return [w for w in words if w.lower() not in _ORG_GENERIC]


# Реквизиты

# Число рядом с подписью, без контрольной суммы. Пары "ИНН/КПП" - в PAIRED_REQUISITE_RE.
REQUISITE_RE = re.compile(
    r"(?<![/\w])(ИНН|ОГРНИП|ОГРН|КПП|БИК|ОКПО|ОКТМО|ОКВЭД"
    r"|рег(?:истрационный)?\.?[ \t]*(?:номер|№))"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{3,15})(?![ \t]*/[ \t]*\d)",
    re.IGNORECASE,
)

# "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку
_REQ_WORD = r"(?:ИНН|ОГРНИП|ОГРН|КПП|БИК|ОКПО|ОКТМО)"
PAIRED_REQUISITE_RE = re.compile(
    rf"({_REQ_WORD}(?:[ \t]*(?:/|и)[ \t]*{_REQ_WORD})+)"
    rf"[^\d\n]{{0,80}}?"
    rf"(\d{{3,15}}(?:[ \t]*/[ \t]*\d{{0,15}})+)",
    re.IGNORECASE,
)
_SPLIT_LABELS = re.compile(r"[ \t]*(?:/|и)[ \t]*")
_SPLIT_NUMS = re.compile(r"[ \t]*/[ \t]*")


# "Договор № 12/24 от 25.01.2023" -> "Договор {{DOCREF_1}} от {{DATE_1}}".
# Ищем по слову, а не по "№": просто "№ 4" в КУДиР маскировать нельзя.
_DOC_ANCHOR = (
    r"(?:договор\w*|доверенност\w+|контракт\w*|соглашени\w+|спецификаци\w+"
    r"|заявлени\w+(?:[ \t]*-[ \t]*оферт\w+)?|оферт\w+"
    r"|сч[её]т[ \t]*-?[ \t]*фактур\w+|сч[её]т\w*|накладн\w+|УПД|УКД"
    r"|акт\w*|платежн\w+[ \t]+поручени\w+)"
)
# до шести слов между "договор" и номером, без цифр и широких отступов
_DOC_GAP = r"(?:[ \t]{1,3}[А-ЯA-Zа-яa-z][А-ЯA-Zа-яa-z-]{0,19}\.?){0,6}"

_MONTH_STEMS = r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
_DATE = rf"(?:\d{{1,2}}[.\-/]\d{{1,2}}[.\-/]\d{{2,4}}|\d{{1,2}}[ \t]+{_MONTH_STEMS}[ \t]+\d{{4}}(?:[ \t]+год\w*)?)"

# "от 01.09.2026" за номером, найденным не через DOCREF_RE
DATE_AFTER_RE = re.compile(rf"[ \t]{{0,3}}от[ \t]{{0,3}}({_DATE})", re.IGNORECASE)

DOCREF_RE = re.compile(
    rf"{_DOC_ANCHOR}{_DOC_GAP}"
    r"[ \t]{0,3}(№|N|N°)?[ \t]{0,3}"
    r"(?<![\w-])([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/._]{1,30})"
    rf"(?:[ \t]{{1,3}}от[ \t]{{1,3}}({_DATE}))?",
    re.IGNORECASE,
)

# серийный номер сертификата ЭП
CERT_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{16,64}(?![0-9A-Za-z])")

# Адрес: нужны и улица, и номер дома
_STREET = (
    r"(?:ул|улиц\w+|пр-?кт|проспект\w*|пер|переул\w+|наб|набережн\w+"
    r"|ш|шоссе|б-р|бульвар\w*|пл|площад\w+|прое?зд\w*|туп|тупик\w*)"
)
# "ул. Каланчевская" и "Тверская ул."
_ADDR_HEAD = (
    rf"(?:{_STREET}\.?{_WRAP}[А-ЯЁ][\w.-]*(?:{_WRAP}[А-ЯЁа-яё][\w.-]*){{0,3}}"
    rf"|[А-ЯЁ][\w.-]*(?:{_WRAP}[А-ЯЁа-яё][\w.-]*){{0,2}}{_WRAP}{_STREET}\.?)"
)
_ADDR_REGION = rf"(?:[А-ЯЁ][а-яё-]+{_WRAP}(?:обл|край|респ|окр|р-н)\w*\.{{0,2}},?{_WRAP})?"
# точка обязательна, иначе "с" найдется внутри "Москва"
_ADDR_CITY = rf"(?:(?<![А-Яа-яЁё])(?:г|гор|пос|пгт|с|дер|город)\.{_WRAP}[А-ЯЁ][а-яё-]+,?{_WRAP})?"
_ADDR_DISTRICT = (rf"(?:(?<![А-Яа-яЁё])(?:г\.[ \t]?о\.|городской{_WRAP}округ)"
                  rf"{_WRAP}[А-ЯЁ][а-яё-]+,?{_WRAP})?")
_ADDR_TAIL = (
    rf"д(?:ом)?\.?{_WRAP}\d+[А-Яа-я]?"
    rf"(?:[,\s]*(?:корп|стр|к|с)\w*\.?{_WRAP}\d+[А-Яа-я]?)?"
    rf"(?:[,\s]*кв\w*\.?{_WRAP}\d+)?"
)
ADDRESS_RE = re.compile(
    rf"(?:\d{{6}},?{_WRAP})?{_ADDR_REGION}{_ADDR_DISTRICT}{_ADDR_CITY}"
    rf"(?<![А-Яа-яЁё]){_ADDR_HEAD},?{_WRAP}{_ADDR_TAIL}",
    re.IGNORECASE,
)
# "д.35, кв.47" без улицы: улицу по фамилии NER мог забрать как персону
ADDRESS_TAIL_RE = re.compile(
    rf"д(?:ом)?\.?{_WRAP}\d+[А-Яа-я]?[,\s]*кв\w*\.?{_WRAP}\d+", re.IGNORECASE
)
# от индекса до конца строки или широкого отступа - адреса нестандартного вида
ADDRESS_RUN_RE = re.compile(
    r"(?<!\d)\d{6},[ \t]?(?:[^\n]{0,120}?)(?=\n|[ \t]{3,}|$)",
)

# индекс, за которым в 60 знаках идут регион или улица ("г." не признак - это и "год")
ADDRESS_INDEX_RE = re.compile(
    rf"(?<!\d)\d{{6}}(?=,[\s\S]{{0,60}}?"
    rf"(?:обл\.|область|край\b|респ\w*\.|округ|р-н|ул\.|улиц|пр-кт|просп|пер\.|шоссе))",
    re.IGNORECASE,
)

# номера, отделенные от слова фразой: "Лицензия на ... №1326"
DOC_REQUISITE_RES = (
    # "серия 77 № 007893219"
    re.compile(r"сери[яи][ \t\n]*(\d{2,4})[ \t\n]*№?[ \t\n]*(\d{5,9})", re.IGNORECASE),
    re.compile(r"договор\w*[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"соглашени\w*[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"(?:лицензи\w+|свидетельств\w+)[^№]{0,120}№[ \t]*(\d[\d-]{2,20})", re.IGNORECASE),
    re.compile(r"регистрационный[ \t\n]+номер[^:]{0,90}:[ \t\n]*(\d{3,15})", re.IGNORECASE),
)
# свои типы, чтобы работали при выключенном REQ
_REQ_TYPE = {"инн": "INN", "огрн": "OGRN", "огрнип": "OGRN", "кпп": "KPP",
             "бик": "BIK"}

# счет - только рядом с подписью, иначе попадут штрихкоды
ACCOUNT_RE = re.compile(
    r"(?<![/\w])(Сч\.?[ \t]*№?|счет|счёт|р/с|к/с|расч\w*[ \t]+счет\w*"
    r"|корр\w*[ \t]+счет\w*)"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{20})(?!\d)",
    re.IGNORECASE,
)


# ФИО, которые NER не берет: КАПСОМ (признак - отчество) и с инициалами
_CAPS_WORD = r"[А-ЯЁ]{2,}(?:-[А-ЯЁ]{2,})?"
# без голого "ИЧ" - иначе КИРПИЧ
_PATR_TAIL = r"(?:ОВИЧ|ЕВИЧ|ЬИЧ|ОВНА|ЕВНА|ИЧНА)"
_CAPS_PATR = rf"[А-ЯЁ]{{3,}}{_PATR_TAIL}"
# в PDF ФИО бывает по слову на строку
_FIO_SEP = r"(?:[ \t]+\n?[ \t]*|\n[ \t]*\n?[ \t]*)"
CAPS_FIO_RE = re.compile(
    rf"(?<![А-ЯЁ\w])(?:"
    # ФАМИЛИЯ ИМЯ ОТЧЕСТВО, фамилия может быть двойной
    rf"{_CAPS_WORD}{_FIO_SEP}(?:{_CAPS_WORD}{_FIO_SEP})?{_CAPS_WORD}{_FIO_SEP}{_CAPS_PATR}"
    rf"|{_CAPS_WORD}{_FIO_SEP}{_CAPS_PATR}{_FIO_SEP}{_CAPS_WORD}"  # ИМЯ ОТЧЕСТВО ФАМИЛИЯ
    rf"|{_CAPS_WORD}{_FIO_SEP}{_CAPS_PATR}"                        # ИМЯ ОТЧЕСТВО
    rf")(?![А-ЯЁ\w])"
)
CAPS_PATR_RE = re.compile(rf"(?<![А-ЯЁ\w])[А-ЯЁ]{{3,}}{_PATR_TAIL}(?![А-ЯЁ\w])")
_SURNAME = r"(?:[А-ЯЁ][а-яё]{2,}|[А-ЯЁ]{3,})"
INITIALS_RE = re.compile(
    rf"(?<![А-ЯЁ\w]){_SURNAME}[ \t]+[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.(?!\w)"
    rf"|(?<![А-ЯЁ\w])[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.[ \t]?{_SURNAME}(?![А-ЯЁ\w])"
)

URL_SCHEME_RE = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.IGNORECASE)
# без http - только www. или свои зоны: иначе core.py и README.md станут доменами
BARE_DOMAIN_RE = re.compile(
    r"(?<![@\w./-])(?:www\.[a-z0-9-]+(?:\.[a-z0-9-]+)*"
    r"|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:ru|com|org|net|io|co|biz|info|рф))"
    r"(?![\w@])(?:/[^\s<>\"'`)\]}]*)?",
    re.IGNORECASE,
)
STOP_HOSTS = frozenset({
    "github.com", "gitlab.com", "bitbucket.org", "stackoverflow.com",
    "python.org", "docs.python.org", "wikipedia.org", "ru.wikipedia.org",
    "habr.com", "example.com", "example.org", "example.net",
})


def _url_host(url: str) -> str:
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0]
    return host.lower().removeprefix("www.")


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def luhn_ok(num: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(num)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def inn_ok(num: str) -> bool:
    def ctrl(digs: str, koef: list[int]) -> int:
        return sum(int(d) * k for d, k in zip(digs, koef)) % 11 % 10

    if len(num) == 10:
        return ctrl(num[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(num[9])
    if len(num) == 12:
        k11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        k12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        return ctrl(num[:10], k11) == int(num[10]) and ctrl(num[:11], k12) == int(num[11])
    return False


def ogrn_ok(num: str) -> bool:
    if len(num) == 13:
        return int(num[:12]) % 11 % 10 == int(num[12])
    if len(num) == 15:
        return int(num[:14]) % 13 % 10 == int(num[14])
    return False


def snils_ok(num: str) -> bool:
    if len(num) != 11:
        return False
    body, chk = num[:9], int(num[9:])
    s = sum(int(body[i]) * (9 - i) for i in range(9))
    if s < 100:
        expected = s
    elif s in (100, 101):
        expected = 0
    else:
        expected = s % 101
        if expected == 100:
            expected = 0
    return chk == expected


# "github: raz00mt"
PROFILE_NICK_RE = re.compile(
    r"\b(?:github|gitlab|bitbucket|habr|behance|dribbble|kaggle|hh|linkedin)"
    r"\s*[:：]\s*([A-Za-z][\w.-]{2,38})", re.IGNORECASE)

# только дата рождения; прочие даты не трогаем
_MONTH = rf"(?:{_MONTH_STEMS})[а-яё]*"
BIRTH_DATE_RE = re.compile(
    r"(?:родил(?:ся|ась)|дата\s+рождения\s*[:\-]?|д\.?\s?р\.?\s*[:\-]?)\s*"
    rf"(\d{{1,2}}[./]\d{{1,2}}[./]\d{{2,4}}|\d{{1,2}}\s+(?:{_MONTH})\w*\s+\d{{4}})",
    re.IGNORECASE)

RESIDENCE_RE = re.compile(
    r"(?:проживает|проживание|город проживания|место жительства|город)\s*[:\-]\s*"
    r"([А-ЯЁ][а-яё]+(?:[ -][А-ЯЁ][а-яё]+){0,2})",
    re.IGNORECASE)


def find_format_entities(text: str, org_names: tuple[str, ...] = ()) -> list[Entity]:
    """Найти форматные ПД. org_names - словарь организаций (load_org_dict)."""
    out: list[Entity] = []

    for m in PROFILE_NICK_RE.finditer(text):
        out.append(Entity("TG", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="profile"))

    for m in BIRTH_DATE_RE.finditer(text):
        out.append(Entity("DATE", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="birth"))

    for m in RESIDENCE_RE.finditer(text):
        out.append(Entity("ADDRESS", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="residence"))

    for m in EMAIL_RE.finditer(text):
        if not FAKE_EMAIL_RE.match(m.group()):
            out.append(Entity("EMAIL", m.group(), m.start(), m.end(), m.group().lower()))

    for m in TG_RE.finditer(text):
        out.append(Entity("TG", m.group(), m.start(), m.end(), m.group().lower()))

    for rx in (URL_SCHEME_RE, BARE_DOMAIN_RE):
        for m in rx.finditer(text):
            url = m.group().rstrip(".,;:!?")
            if _url_host(url) in STOP_HOSTS:
                continue
            out.append(Entity("URL", url, m.start(), m.start() + len(url), url.lower()))

    for m in PHONE_RE.finditer(text):
        d = digits(m.group())
        if d[1:4] != FAKE_PHONE_CODE:
            out.append(Entity("PHONE", m.group(), m.start(), m.end(), d))

    for m in CARD_RE.finditer(text):
        d = digits(m.group())
        if len(d) == 16 and luhn_ok(d):
            out.append(Entity("CARD", m.group(), m.start(), m.end(), d))

    for m in SNILS_RE.finditer(text):
        d = digits(m.group())
        if snils_ok(d):
            out.append(Entity("SNILS", m.group(), m.start(), m.end(), d))

    for m in INN_RE.finditer(text):
        d = m.group()
        if inn_ok(d):
            # без подписи "ИНН" - строгий режим ядра это учитывает
            out.append(Entity("INN", d, m.start(), m.end(), d, source="bare"))

    for m in CERT_RE.finditer(text):
        v = m.group()
        if not (any(c.isdigit() for c in v) and any(c.isalpha() for c in v)):
            continue
        out.append(Entity("CERT", v, m.start(), m.end(), v.lower()))

    for m in DOCREF_RE.finditer(text):
        num = m.group(2)
        if not any(ch.isdigit() for ch in num):
            continue
        # без "№" голое число - скорее сумма
        if not m.group(1) and num.isdigit():
            continue
        out.append(Entity("DOCREF", num, m.start(2), m.end(2), num.lower(),
                          source="docref"))
        if m.group(3):
            out.append(Entity("DATE", m.group(3), m.start(3), m.end(3),
                              m.group(3), source="docref"))

    for m in PAIRED_REQUISITE_RE.finditer(text):
        labels = _SPLIT_LABELS.split(m.group(1))
        nums = _SPLIT_NUMS.split(m.group(2))
        if len(labels) != len(nums):
            # не угадываем, где ИНН, а где КПП
            continue
        pos = m.start(2)
        for label, num in zip(labels, nums):
            if not num:
                continue        # у ИП нет КПП
            start = text.index(num, pos)
            etype = _REQ_TYPE.get(label.strip().lower(), "REQ")
            out.append(Entity(etype, num, start, start + len(num), num,
                              source="requisite"))
            pos = start + len(num)

    for m in REQUISITE_RE.finditer(text):
        num = m.group(2)
        etype = _REQ_TYPE.get(m.group(1).lower(), "REQ")
        out.append(Entity(etype, num, m.start(2), m.end(2), num, source="requisite"))

    for m in ACCOUNT_RE.finditer(text):
        num = m.group(2)
        out.append(Entity("ACCOUNT", num, m.start(2), m.end(2), num, source="requisite"))

    # оставляем самую полную находку адреса
    addrs = [(m.start(), m.end(), m.group())
             for rx in (ADDRESS_RE, ADDRESS_TAIL_RE, ADDRESS_RUN_RE, ADDRESS_INDEX_RE)
             for m in rx.finditer(text)]
    for start, end, txt in addrs:
        if any(a <= start and end <= b and (a, b) != (start, end) for a, b, _ in addrs):
            continue
        out.append(Entity("ADDRESS", txt, start, end, " ".join(txt.lower().split())))

    for rx in DOC_REQUISITE_RES:
        for m in rx.finditer(text):
            for g in range(1, (m.lastindex or 0) + 1):
                if m.group(g):
                    out.append(Entity("REQ", m.group(g), m.start(g), m.end(g), m.group(g)))

    # Слова названий (stems) ищем по документу только от регулярок: ошибку NER
    # это размножило бы по всему тексту.
    quoted: list[tuple[int, int]] = []
    stems: set[str] = set()
    for m in ORG_GENERIC_QUOTED_RE.finditer(text):
        out.append(Entity("ORG", m.group(1), m.start(1), m.end(1),
                          m.group(1).strip('«»"').lower()))

    for rx in (ORG_QUOTED_RE, ORG_TRAILING_FORM_RE):
        for m in rx.finditer(text):
            name = m.group()
            if any(s <= m.start() and m.end() <= e for s, e in quoted):
                continue
            quoted.append((m.start(), m.end()))
            stems.update(_org_stems(name))
            out.append(
                Entity("ORG", name, m.start(), m.end(), " ".join(name.lower().split()))
            )

    # последним: «Ромашка» внутри 'АО «Ромашка»' не выдаем второй раз
    for m in ORG_QUOTED_NAME_RE.finditer(text):
        name = m.group(1)
        if len(name) < 3:
            continue
        if any(e.type == "ORG" and e.start <= m.start(1) and m.end(1) <= e.end
               for e in out):
            continue
        out.append(Entity("ORG", name, m.start(1), m.end(1), name.lower()))

    # словарь: сначала название целиком, чтобы "Ромашка Россия" была одной меткой
    for name in org_names:
        flags = re.IGNORECASE if len(name) > 3 else 0
        pat = rf"(?<!{_WORD_CHAR}){re.escape(name)}(?!{_WORD_CHAR})"
        for m in re.finditer(pat, text, flags):
            if any(s <= m.start() and m.end() <= e for s, e in quoted):
                continue
            quoted.append((m.start(), m.end()))
            out.append(
                Entity("ORG", m.group(), m.start(), m.end(),
                       " ".join(name.lower().split()), source="dict")
            )

    # потом по словам - для названий, разорванных версткой
    for name in org_names:
        stems.update(_org_stems(name))
    stems |= set(_prefixes(stems))
    for stem in stems:
        # короткие - с учетом регистра: "ОКБ" да, "окб" нет
        flags = re.IGNORECASE if len(stem) > 3 else 0
        bound = _WORD_CHAR
        for hit in re.finditer(rf"(?<!{bound}){re.escape(stem)}(?!{bound})", text, flags):
            if any(s <= hit.start() and hit.end() <= e for s, e in quoted):
                continue
            out.append(Entity("ORG", hit.group(), hit.start(), hit.end(), stem.lower()))

    for m in OGRN_RE.finditer(text):
        d = m.group()
        if ogrn_ok(d):
            out.append(Entity("OGRN", d, m.start(), m.end(), d))

    uids: list[tuple[int, int, str]] = []
    for rx in (UID_RE, UID_LOOSE_RE):
        for m in rx.finditer(text):
            if len(re.findall(r"[0-9a-f]", m.group(), re.IGNORECASE)) >= _UID_MIN_HEX:
                uids.append((m.start(), m.end(), m.group()))
    for start, end, txt in uids:
        if any(s <= start and end <= e and (s, e) != (start, end) for s, e, _ in uids):
            continue
        out.append(Entity("UID", txt, start, end, txt.lower()))

    # "паспорт" в 40 знаках перед номером или где угодно в документе про паспорта
    whole_doc = bool(PASSPORT_DOC_CTX_RE.search(text))
    for m in PASSPORT_RE.finditer(text):
        window = text[max(0, m.start() - 40):m.start()]
        if whole_doc or PASSPORT_CTX_RE.search(window):
            out.append(Entity("PASSPORT", m.group(), m.start(), m.end(), digits(m.group())))

    named: list[tuple[int, int]] = []
    fio_words: set[str] = set()
    for rx in (CAPS_FIO_RE, INITIALS_RE):
        for m in rx.finditer(text):
            named.append((m.start(), m.end()))
            out.append(Entity("PERSON", m.group(), m.start(), m.end(),
                              " ".join(m.group().lower().split())))
            if rx is CAPS_FIO_RE:
                fio_words.update(w for w in re.findall(r"[А-ЯЁ-]{4,}", m.group()))
    for m in CAPS_PATR_RE.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in named):
            continue
        out.append(Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower()))

    # одинокое слово капсом из уже найденного ФИО ("ВЕРШКОВА" на своей строке в PDF)
    known_fio = {w: w for w in fio_words} | _prefixes(fio_words)
    for hit in re.finditer(r"(?<![А-ЯЁA-Za-zа-яё-])[А-ЯЁ-]{4,}(?![А-ЯЁA-Za-zа-яё-])", text):
        if hit.group() not in known_fio:
            continue
        if any(s <= hit.start() and hit.end() <= e for s, e in named):
            continue
        out.append(Entity("PERSON", hit.group(), hit.start(), hit.end(), hit.group().lower()))

    # дубли одного спана: оставляем находку с более надежным источником
    rank = {"dict": 3, "requisite": 2, "": 1, "bare": 0}
    best: dict[tuple[str, int, int], Entity] = {}
    order: list[tuple[str, int, int]] = []
    for ent in out:
        mark = (ent.type, ent.start, ent.end)
        if mark not in best:
            best[mark] = ent
            order.append(mark)
        elif rank.get(ent.source, 1) > rank.get(best[mark].source, 1):
            best[mark] = ent
    return [best[m] for m in order]


def load_org_dict(path) -> tuple[str, ...]:
    """Словарь названий организаций: по одному на строку, '#' - комментарий."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"словарь организаций не найден: {p}")
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return tuple(names)
