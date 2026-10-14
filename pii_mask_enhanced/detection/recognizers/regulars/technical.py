"""Технические идентификаторы: логи, заголовки HTTP, выгрузки устройств."""
import re

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
