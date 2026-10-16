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

# Учетные данные. Пара "логин/пароль: ivanov / Qwerty123": значения по порядку подписей
LOGIN_PASSWORD_RE = re.compile(
    r"(?<!\w)(?:логин|login)[ \t]*/[ \t]*(?:пароль|password)[ \t]*[:=][ \t]*"
    r"(\S+?)[ \t]*/[ \t]*([^\s,;]+)", re.IGNORECASE)
# в адресе: "https://ivanov:Qwerty123@host" - хост остается адресом (finders/contacts)
URL_CREDS_RE = re.compile(r"(?<=://)([^:/@\s]+):([^@/\s]+)@")
# доменная учетная запись Windows "CORP\ivanov_i"; "\" вокруг - уже путь: "C:\WINDOWS\system32"
DOMAIN_LOGIN_RE = re.compile(r"(?<![\w\\:])[A-Z][A-Z0-9-]{1,14}\\[A-Za-z][\w.-]{1,63}(?![\w\\])")

# Хэш пароля в формате crypt
PASSWORD_HASH_RE = re.compile(
    r"(?<![\w$])(?:\$(?:2[abxy]|argon2(?:id|i|d)|1|5|6|y|gy|7|apr1|scrypt|pbkdf2(?:-sha\d+)?)\$"
    r"|(?:pbkdf2_sha(?:1|256)|bcrypt_sha256|argon2)\$)[\w./+=$,-]{16,}")
# hex md5/sha1/sha256/sha512
HEX_HASH_RE = re.compile(
    r"(?<![\w-])(?:hash|password[_-]?hash|pass[_-]?hash|хэш\w*|хеш\w*|digest|md5|sha-?1|sha-?256"
    r"|sha-?512|ntlm|nthash)[\"']?[ \t]*[=:]?[ \t]*[\"']?"
    r"([0-9a-f]{128}|[0-9a-f]{64}|[0-9a-f]{40}|[0-9a-f]{32})(?![0-9a-f])", re.IGNORECASE)
# дамп SAM/secretsdump "user:1001:LM:NT:::" - имя и оба хэша
NTLM_DUMP_RE = re.compile(r"(?m)^([^:\s]{1,64}):\d{1,10}:([0-9a-fA-F]{32}):([0-9a-fA-F]{32}):::")

# Ключи. PEM-блок закрывается без заголовков: по ним видно, что за ключ.
# Сертификат и открытый ключ - тоже: в сертификате ФИО и организация владельца
PEM_RE = re.compile(r"-----BEGIN ([A-Z0-9 ]{3,40})-----(.+?)-----END \1-----", re.DOTALL)
# открытый SSH-ключ: тело - секрет, комментарий "ivanov@host" - логин владельца
SSH_KEY_RE = re.compile(
    r"(?<![\w-])(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-nistp\d{3})[ \t]+(AAAA[\w+/]{16,}=*)"
    r"(?:[ \t]+([^\s]+@[^\s]+))?")
# Токены сервисов с узнаваемым префиксом
API_TOKEN_RE = re.compile(
    r"(?<![\w-])(?:"
    r"(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[0-9A-Z]{16}"      # AWS
    r"|gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_\w{22,255}"  # GitHub
    r"|glpat-[\w-]{20,}"                                  # GitLab
    r"|xox[abposr]-[0-9A-Za-z-]{10,}"                     # Slack
    r"|AIza[\w-]{35}"                                     # Google
    r"|sk-(?:proj-|ant-(?:api|admin)\d{2}-)?[\w-]{20,}"   # OpenAI, Anthropic
    r"|(?:sk|rk)_live_[0-9A-Za-z]{16,}"                   # Stripe
    r"|y[0-3]_[\w-]{40,}|AQAAAA[\w-]{30,}"                # Яндекс OAuth
    r"|\d{8,10}:AA[\w-]{33}"                              # бот Telegram
    r")(?![\w-])")
# Секрет по ключу конфига: "client_secret=...", "PRIVATE_KEY: ...", "DB_PASSWORD_KEY=...".
# Значение проверяется на энтропию (finders/technical): "secret: none", "KEY=default"
SECRET_KEY_RE = re.compile(
    r"(?<![\w-])(?:\w*(?:secret|private[_-]?key|access[_-]?key|signing[_-]?key|encryption[_-]?key"
    r"|master[_-]?key)\w*|(?-i:[A-Z][A-Z0-9_]*_(?:KEY|SECRET|TOKEN))"
    r"|(?:секретн\w*|закрыт\w*|приватн\w*)[ \t]+ключ\w*|ключ\w*[ \t]+(?:шифровани|доступа|API)\w*)"
    r"[\"']?[ \t]*[=:][ \t]*[\"']?([\w.~+/=-]{16,})", re.IGNORECASE)

# строка браузера: заголовок или узнаваемое начало "Mozilla/5.0 (...)"
USER_AGENT_HEADER_RE = re.compile(r"User-Agent[ \t]*[:=][ \t]*[\"']?([^\r\n\"']+)", re.IGNORECASE)
USER_AGENT_RE = re.compile(r"(?<![\w/])Mozilla/\d\.\d[ \t]+\([^)\n]*\)[^\r\n\"']*")
