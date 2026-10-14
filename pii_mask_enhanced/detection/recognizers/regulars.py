import re
from dataclasses import dataclass
from typing import Callable

from ..registry.entity_types import REQUISITE_WORD
from ..registry.id_documents import DOCS
from ..registry.labelled_values import VALUES
from ..registry.legal_forms import ORG_FORM, TRAILING_FORM
from . import helpers
from .entity import digits, text_key

FAKE_PHONE_CODE = "000"
FAKE_EMAIL_RE = re.compile(r"^user\d+@example\.com$", re.IGNORECASE)

# Российский номер: 10 цифр после +7, 7 или 8. Код города - 3, 4 или 5 цифр, остаток
# добирает до десяти; внутри остатка группы любые ("1-23-45", "123 4567").
def _digits_run(n: int) -> str:
    return rf"\d(?:[ \-]?\d){{{n - 1}}}"

PHONE_EXT = r"(?:[ \t]*,?[ \t]*(?:доб|ext|вн)\.?[ \t]*\d{1,6})"
PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+[ ]?7|[78])[ \-]?(?:"
    rf"\(?\d{{3}}\)?[ \-]?{_digits_run(7)}"
    rf"|\(\d{{4}}\)[ \-]?{_digits_run(6)}"
    rf"|\(\d{{5}}\)[ \-]?{_digits_run(5)}"
    rf"){PHONE_EXT}?(?!\d)",
    re.IGNORECASE,
)

PHONE_LOCAL_RE = re.compile(
    r"(?<!\w)(?:телефон\w*|тел|т|факс|моб|сот)\.?[ \t]*(?:[:№][ \t]*)?"
    rf"(\d{{1,3}}-\d{{2}}-\d{{2}}{PHONE_EXT}?)(?![\d-])",
    re.IGNORECASE,
)
# международный префикс "00" вместо "+": "00 44 20 7946 0958"
PHONE_IDD_RE = re.compile(r"(?<![\w+(])(?<!\d[ \-])00 ?(?=[1-9])")
EMAIL_RE = re.compile(r"[\w.%+\-]+@[\w.\-]+\.(?:[A-Za-zА-Яа-яЁё]{2,}|xn--[a-z0-9\-]+)")
TG_RE = re.compile(r"(?<![\w.\-@])@[A-Za-z][A-Za-z0-9_]{4,31}\b")

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


@dataclass(frozen=True)
class LabelledValueRe:
    """Значение по подписи из registry/labelled_values, собранное в регулярки."""
    name: str
    type: str
    # в тексте: подпись, разделитель, значение (группа 1)
    text: re.Pattern
    # в таблице: подпись и значение в соседних ячейках
    cell_label: re.Pattern
    cell_value: re.Pattern
    # ключ консистентности находки: одинаковый ключ - одна метка
    key: Callable[[str], str]


def _labelled_value(v) -> LabelledValueRe:
    # "N" вместо "№" - только перед пробелом или цифрой: иначе это первая буква значения
    sep = r"[ \t]*[:=][ \t]*" if v.needs_sep else r"[ \t]*(?:(?:[:=№]|N(?=[ \t\d]))[ \t]*)?"
    value = rf"(?-i:{v.value})"
    return LabelledValueRe(
        v.name, v.type,
        re.compile(rf"(?<!\w)(?:{v.label})(?!\w){sep}\n?[ \t]*({value})", re.IGNORECASE),
        re.compile(rf"^\s*(?:{v.label})\s*(?:№|N)?\s*[:=]?\s*$", re.IGNORECASE),
        re.compile(rf"^\s*{value}\s*$"),
        digits if v.digits_key else text_key,
    )


LABELLED_VALUES = tuple(_labelled_value(v) for v in VALUES)
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

# для проверки находок NER (Masker.ner_org_needs_form)
ORG_FORM_RE = re.compile(rf"\b{ORG_FORM}\b", re.IGNORECASE)

ORG_QUOTED_RE = re.compile(
    rf"{ORG_FORM}[ \t]*\n?[ \t]*[«\"][^»\"]{{2,80}}[»\"]", re.IGNORECASE
)

ORG_TRAILING_FORM_RE = re.compile(
    r"(?<![\w-])(?:[А-ЯЁA-Z][\w-]*[ \t]+){0,2}[А-ЯЁA-Z][\w-]*"
    rf"[ \t]*,[ \t]*{TRAILING_FORM}(?![\w-])(?![ \t]+[«\"А-ЯЁA-Z])"
)

# родовое слово + название в кавычках: 'ТРЦ "Ромашка"', 'БЦ "Полевой"'
_ORG_TYPE_GENERIC = (
    r"(?:ТРЦ|ТЦ|БЦ|ЖК|МФК|ТПУ|СРО|НИИ|КБ|завод|комбинат|фабрика|агентство"
    r"|холдинг|группа|управление|департамент)"
)
ORG_GENERIC_QUOTED_RE = re.compile(
    rf"(?<![\w-]){_ORG_TYPE_GENERIC}[ \t]+([«\"][^»\"\n]{{2,80}}[»\"])", re.IGNORECASE
)

ORG_QUOTED_NAME_RE = re.compile(
    r"[«\"“]((?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)(?:[ \t](?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)){0,2})[»\"”]")

# Число рядом с подписью, без контрольной суммы. Пары "ИНН/КПП" - в PAIRED_REQUISITE_RE.
REQUISITE_RE = re.compile(
    rf"(?<![/\w])({REQUISITE_WORD}"
    r"|рег(?:истрационный)?\.?[ \t]*(?:номер|№))"
    r"[ \t]*(?:№|:)?[ \t]*\n?[ \t]*(\d{3,15})(?![ \t]*/[ \t]*\d)",
    re.IGNORECASE,
)

# "ИНН/КПП 6083778353/770101001": подписи и числа сопоставляются по порядку
PAIRED_REQUISITE_RE = re.compile(
    rf"({REQUISITE_WORD}(?:[ \t]*(?:/|и)[ \t]*{REQUISITE_WORD})+)"
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

# Номер из сегментов через "/" или "-": "12345/ФЛ", "ФЛ-12345", "625/0000-0123456 / ЮЛ"
DOC_SEGMENTS_RE = re.compile(
    r"(?<![\w./-])\w+(?:\.\w+)*(?:(?:-|[ \t]?/[ \t]?)\w+(?:\.\w+)*)+(?![\w/-])"
)
DOC_SEGMENT_SEP_RE = re.compile(r"[ \t]?[/-][ \t]?")

# серийный номер сертификата ЭП
CERT_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{16,64}(?![0-9A-Za-z])")

# Счет и код инвестора по подписи - в registry/labelled_values.
# Торговый код фондового рынка Мосбиржи узнается и без подписи; М и С бывают кириллицей
MOEX_CODE_RE = re.compile(r"(?<!\w)[MМ][CС]\d{10}(?!\w)")

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
    rf"(?<![А-Яа-яЁё])д(?:ом)?\.?{helpers.WRAP}\d+[А-Яа-я]?[,\s]*кв\w*\.?{helpers.WRAP}\d+",
    re.IGNORECASE
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
    re.compile(r"(?:договор\w*|(?<!\w)ДБО)[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"соглашени\w*[^№]{0,130}№[ \t]*([\w/\-.]+)", re.IGNORECASE),
    re.compile(r"(?:лицензи\w+|свидетельств\w+)[^№]{0,120}№[ \t]*(\d[\d-]{2,20})", re.IGNORECASE),
    re.compile(r"регистрационный[ \t\n]+номер[^:]{0,90}:[ \t\n]*(\d{3,15})", re.IGNORECASE),
)

PROFILE_NICK_RE = re.compile(
    r"\b(?:github|gitlab|bitbucket|habr|behance|dribbble|kaggle|hh|linkedin)"
    r"\s*[:：]\s*([A-Za-z][\w.-]{2,38})", re.IGNORECASE)

# только дата рождения; прочие даты не трогаем
BIRTH_DATE_RE = re.compile(
    r"(?:родил(?:ся|ась)|дата\s+рожд\w*\.?\s*[:\-]?|д\.?\s?р\.?\s*[:\-]?)\s*"
    rf"({helpers.DATE})",
    re.IGNORECASE)
# год рождения: "1985 г.р.", "г.р. 1985"; точка обязательна, иначе "500 гр" - граммы
BIRTH_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[ \t]*г\.[ \t]?р\.?(?!\w)"
    r"|(?<!\w)г\.[ \t]?р\.[ \t]*((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE)

# дата выдачи с необязательным "г.": "12 марта 2015 г."
ISSUE_DATE_RE = re.compile(rf"{helpers.DATE}(?:[ \t]*г(?:од\w*|\.))?", re.IGNORECASE)
# хвост за паспортом или документом: "выдан ОВД района Арбат 12.03.2015, код подразделения 770-001"
ISSUE_AFTER_RE = re.compile(
    r"[ \t,.;]*(?:кем[ \t]+)?(?:выдан\w*|дата[ \t]+выдачи)[ \t:]*([^\n]{3,160})", re.IGNORECASE)
# код подразделения
UNIT_CODE_RE = re.compile(r"код\w*[ \t]+подразделени\w*[ \t:№]*(\d{3}[ \t-]?\d{3})(?!\d)",
                          re.IGNORECASE)

ISSUE_DATE_LABEL_RE = re.compile(rf"дата[ \t]+выдачи[ \t:]*\n?[ \t]*({ISSUE_DATE_RE.pattern})",
                                 re.IGNORECASE)
ISSUER_LABEL_RE = re.compile(
    r"(?:кем[ \t]+выдан\w*|орган\w*,?[ \t]+выдавш\w+[ \t]+(?:документ|паспорт)\w*)[ \t:]*\n?[ \t]*"
    r"([^\n]{3,120})", re.IGNORECASE)
# орган выдачи кончается на запятой, широкой отбивке или границе колонки
ISSUER_END_RE = re.compile(r"[,;|]|[ \t]{3,}")

# срок действия карты: "12/27", "12/2027"
CARD_EXPIRY = r"(?<!\d)(?:0[1-9]|1[0-2])[ \t]?/[ \t]?(?:\d{4}|\d{2})(?!\d)"
_EXPIRY_WORD = (r"(?:срок\w*(?:[ \t]+действия)?(?:[ \t]+карты)?|действ\w*[ \t]+до|годна[ \t]+до"
                r"|valid[ \t]+(?:thru|through)|exp(?:iry|ires|\.)?(?:[ \t]+date)?)")
# сразу за картой подпись не обязательна: "4276 3800 1234 5679 12/27"
EXPIRY_AFTER_RE = re.compile(rf"[ \t,;]*(?:{_EXPIRY_WORD}[ \t:]*)?({CARD_EXPIRY})", re.IGNORECASE)
# где угодно - только у подписи и только "ММ/ГГ": "действует до 31.12.2026" - срок договора
EXPIRY_LABEL_RE = re.compile(rf"(?<!\w){_EXPIRY_WORD}[ \t:]*({CARD_EXPIRY})", re.IGNORECASE)

RESIDENCE_RE = re.compile(
    r"(?:проживает|проживание|город проживания|место жительства|город)\s*[:\-]\s*"
    r"([А-ЯЁ][а-яё]+(?:[ -][А-ЯЁ][а-яё]+){0,2})",
    re.IGNORECASE)

# --- Технические идентификаторы: логи, заголовки HTTP, выгрузки устройств ---

# Кандидаты; адрес проверяет ipaddress
IPV4_RE = re.compile(r"(?<![\w./])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\w)")
IPV6_RE = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")

# "00:1A:2B:3C:4D:5E", "00-1A-2B-3C-4D-5E", "001a.2b3c.4d5e"
MAC_RE = re.compile(
    r"(?<![\w:.-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![\w:.-])"
    r"|(?<![\w.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![\w.])"
)
IMEI_RE = re.compile(
    r"(?<!\w)(?:IMEI(?:SV)?|ИМЕЙ)[ \t]*\d?[ \t]*[:№=]?[ \t]*(\d(?:[ /-]?\d){13,15})(?!\d)",
    re.IGNORECASE,
)

# заголовок.нагрузка.подпись в base64url; без подписи ("alg": "none") подпись пустая
JWT_RE = re.compile(r"(?<![\w-])eyJ[\w-]{5,}\.eyJ[\w-]{5,}\.[\w-]*(?![\w-])")
# значение по ключу; в значении есть цифра: "session: утро" - не идентификатор
SESSION_RE = re.compile(
    r"(?<![\w-])(?:PHPSESSID|JSESSIONID|ASP\.NET_SessionId|session[_-]?id|session|sid|ssid"
    r"|(?:access|refresh|id|auth|csrf)[_-]?token|token|api[_-]?key|yandexuid|_ym_uid|_ga)"
    r"[\"']?[ \t]*[=:][ \t]*[\"']?((?=[\w.~+/%-]*\d)[\w.~+/%-]{6,}=*)",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"(?<!\w)Bearer[ \t]+([\w.~+/-]{10,}=*)", re.IGNORECASE)
# в заголовке cookie закрываем значения, имена оставляем: по ним видно, что за cookie
COOKIE_HEADER_RE = re.compile(r"^[ \t]*(?:Set-)?Cookie[ \t]*:[ \t]*(.+)$",
                              re.IGNORECASE | re.MULTILINE)
COOKIE_PAIR_RE = re.compile(r"(?:^|;)[ \t]*([^=;\s]+)=([^;\r\n]+)")
# атрибуты Set-Cookie - не данные
COOKIE_ATTRS = frozenset({"path", "domain", "expires", "max-age", "samesite"})

# строка браузера: заголовок или узнаваемое начало "Mozilla/5.0 (...)"
USER_AGENT_HEADER_RE = re.compile(r"User-Agent[ \t]*[:=][ \t]*[\"']?([^\r\n\"']+)", re.IGNORECASE)
USER_AGENT_RE = re.compile(r"(?<![\w/])Mozilla/\d\.\d[ \t]+\([^)\n]*\)[^\r\n\"']*")