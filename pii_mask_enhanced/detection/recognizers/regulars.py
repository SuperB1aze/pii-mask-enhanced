import re

from . import helpers

FAKE_PHONE_CODE = "000"
FAKE_EMAIL_RE = re.compile(r"^user\d+@example\.com$", re.IGNORECASE)

PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[ \-]?\(?\d{3}\)?[ \-]?\d{3}[ \-]?\d{2}[ \-]?\d{2}(?!\d)")
EMAIL_RE = re.compile(r"[\w.%+\-]+@[\w.\-]+\.(?:[A-Za-zА-Яа-яЁё]{2,}|xn--[a-z0-9\-]+)")
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
# последняя группа необязательна: хвост в PDF уезжает, а головы хватает
UID_RE = re.compile(
    rf"(?<![\w-])[0-9a-f]{{8}}(?:-{helpers.WRAP}[0-9a-f]{{4}}){{1,3}}"
    rf"(?:-{helpers.WRAP}[0-9a-f]{{12}}(?:-\d{{1,3}})?)?-?(?![\w])",
    re.IGNORECASE,
)
# УИД с потерянными дефисами; меньше 16 hex-знаков - не УИД
UID_LOOSE_RE = re.compile(r"(?<![\w-])[0-9a-f]{8}-[0-9a-f-]{8,48}(?![\w])", re.IGNORECASE)

# Организации
ORG_FORM = (
    r"(?:АО|ОАО|ЗАО|ПАО|НАО|ООО|НКО|АНО|ПК|ГК|ФГУП|МУП|ИП"
    r"|Акционерное\s+общество|Публичное\s+акционерное\s+общество"
    r"|Общество\s+с\s+ограниченной\s+ответственностью"
    r"|Банк|Компания|Бюро|Фонд)"
)

# для проверки находок NER (Masker.ner_org_needs_form)
ORG_FORM_RE = re.compile(rf"\b{ORG_FORM}\b", re.IGNORECASE)

ORG_QUOTED_RE = re.compile(
    rf"{ORG_FORM}[ \t]*\n?[ \t]*[«\"][^»\"]{{2,80}}[»\"]", re.IGNORECASE
)

ORG_TRAILING_FORM_RE = re.compile(
    r"(?<![\w-])(?:[А-ЯЁA-Z][\w-]*[ \t]+){0,2}[А-ЯЁA-Z][\w-]*"
    rf"[ \t]*,[ \t]*{helpers.ORG_FORM_TRAILING}(?![\w-])(?![ \t]+[«\"А-ЯЁA-Z])"
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

# Число рядом с подписью, без контрольной суммы. Пары "ИНН/КПП" - в PAIRED_REQUISITE_RE.
REQUISITE_RE = re.compile(
    r"(?<![/\w])(ИНН|ОГРНИП|ОГРН|КПП|БИК|ОКПО|ОКТМО|ОКВЭД"
    r"|рег(?:истрационный)?\.?[ \t]*(?:номер|№))"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{3,15})(?![ \t]*/[ \t]*\d)",
    re.IGNORECASE,
)

# "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку
PAIRED_REQUISITE_RE = re.compile(
    rf"({helpers.REQ_WORD}(?:[ \t]*(?:/|и)[ \t]*{helpers.REQ_WORD})+)"
    rf"[^\d\n]{{0,80}}?"
    rf"(\d{{3,15}}(?:[ \t]*/[ \t]*\d{{0,15}})+)",
    re.IGNORECASE,
)

# "от 01.09.2026" за номером, найденным не через DOCREF_RE
DATE_AFTER_RE = re.compile(rf"[ \t]{{0,3}}от[ \t]{{0,3}}({helpers.DATE})", re.IGNORECASE)

DOCREF_RE = re.compile(
    rf"{helpers.DOC_ANCHOR}{helpers.DOC_GAP}"
    r"[ \t]{0,3}(№|N|N°)?[ \t]{0,3}"
    r"(?<![\w-])([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/._]{1,30})"
    rf"(?:[ \t]{{1,3}}от[ \t]{{1,3}}({helpers.DATE}))?",
    re.IGNORECASE,
)

# серийный номер сертификата ЭП
CERT_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{16,64}(?![0-9A-Za-z])")

# счет - только рядом с подписью, иначе попадут штрихкоды
ACCOUNT_RE = re.compile(
    r"(?<![/\w])(Сч\.?[ \t]*№?|счет|счёт|р/с|к/с|расч\w*[ \t]+счет\w*"
    r"|корр\w*[ \t]+счет\w*)"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{20})(?!\d)",
    re.IGNORECASE,
)

CAPS_FIO_RE = re.compile(
    rf"(?<![А-ЯЁ\w])(?:"
    # ФАМИЛИЯ ИМЯ ОТЧЕСТВО, фамилия может быть двойной
    rf"{helpers.CAPS_WORD}{helpers.FIO_SEP}(?:{helpers.CAPS_WORD}{helpers.FIO_SEP})?{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}{helpers.FIO_SEP}{helpers.CAPS_WORD}"  # ИМЯ ОТЧЕСТВО ФАМИЛИЯ
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"                        # ИМЯ ОТЧЕСТВО
    rf")(?![А-ЯЁ\w])"
)

CAPS_PATR_RE = re.compile(rf"(?<![А-ЯЁ\w])[А-ЯЁ]{{3,}}{helpers.PATR_TAIL}(?![А-ЯЁ\w])")

INITIALS_RE = re.compile(
    rf"(?<![А-ЯЁ\w]){helpers.SURNAME}[ \t]+[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.(?!\w)"
    rf"|(?<![А-ЯЁ\w])[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.[ \t]?{helpers.SURNAME}(?![А-ЯЁ\w])"
)

URL_SCHEME_RE = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.IGNORECASE)

# очень желательно оставлять сайты с http
# без http - только www. или свои зоны: иначе core.py и README.md станут доменами
LABEL = r"(?:xn--[a-z0-9-]+|[a-zа-яё0-9](?:[a-zа-яё0-9-]*[a-zа-яё0-9])?)"
# ".москва" здесь нет: иначе "г.Москва" станет доменом. Она ловится через HINTED_DOMAIN_RE
TLD = (r"(?:ru|su|com|org|net|io|co|biz|info|moscow"
        r"|рф|рус|онлайн|сайт|орг|дети|xn--p1ai|xn--p1acf)")
URL_PATH = r"(?:/[^\s<>\"'`)\]}]*)?"
BARE_DOMAIN_RE = re.compile(
    rf"(?<![@\w./-])(?:www\.{LABEL}(?:\.{LABEL})*|{LABEL}(?:\.{LABEL})*\.{TLD})"
    rf"(?![\w@]){URL_PATH}",
    re.IGNORECASE,
)

# исключение для ложных срабатываний по домену
FILE_EXT = (r"(?:pdf|docx?|xlsx?|pptx?|odt|rtf|txt|csv|json|xml|ya?ml|md|py|js|ts|sh"
            r"|zip|rar|7z|png|jpe?g|gif|svg|mp[34]|avi|mov|exe|msi|log|ini|cfg)")
# любая буквенная зона, но только после слова-подсказки: "сайт: example.shop"
HINTED_DOMAIN_RE = re.compile(
    r"(?:\b(?:веб-?)?сайт\w*|портал\w*|домен\w*|ссылк\w*|url|website|site|web)"
    r"(?:[ \t]+[\w-]{1,15}){0,2}[ \t]*[:\-–—]?[ \t]*"
    rf"((?<![@\w./-])(?=[\w-]{{2}}){LABEL}(?:\.{LABEL})*"
    rf"\.(?!{FILE_EXT}(?![\w-]))(?:xn--[a-z0-9-]+|[a-zа-яё]{{2,24}})"
    rf"(?![\w@-]){URL_PATH})",
    re.IGNORECASE,
)


ADDRESS_RE = re.compile(
    rf"(?:\d{{6}},?{helpers.WRAP})?{helpers.ADDR_REGION}{helpers.ADDR_DISTRICT}{helpers.ADDR_CITY}"
    rf"(?<![А-Яа-яЁё]){helpers.ADDR_HEAD},?{helpers.WRAP}{helpers.ADDR_TAIL}",
    re.IGNORECASE,
)
# "д.35, кв.47" без улицы: улицу по фамилии NER мог забрать как персону
ADDRESS_TAIL_RE = re.compile(
    rf"д(?:ом)?\.?{helpers.WRAP}\d+[А-Яа-я]?[,\s]*кв\w*\.?{helpers.WRAP}\d+", re.IGNORECASE
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

PROFILE_NICK_RE = re.compile(
    r"\b(?:github|gitlab|bitbucket|habr|behance|dribbble|kaggle|hh|linkedin)"
    r"\s*[:：]\s*([A-Za-z][\w.-]{2,38})", re.IGNORECASE)

# только дата рождения; прочие даты не трогаем
BIRTH_DATE_RE = re.compile(
    r"(?:родил(?:ся|ась)|дата\s+рождения\s*[:\-]?|д\.?\s?р\.?\s*[:\-]?)\s*"
    rf"(\d{{1,2}}[./]\d{{1,2}}[./]\d{{2,4}}|\d{{1,2}}\s+(?:{helpers.MONTH})\w*\s+\d{{4}})",
    re.IGNORECASE)

RESIDENCE_RE = re.compile(
    r"(?:проживает|проживание|город проживания|место жительства|город)\s*[:\-]\s*"
    r"([А-ЯЁ][а-яё]+(?:[ -][А-ЯЁ][а-яё]+){0,2})",
    re.IGNORECASE)