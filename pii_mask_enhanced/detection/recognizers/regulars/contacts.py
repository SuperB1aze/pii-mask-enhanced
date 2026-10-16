"""Контакты: телефон, почта, телеграм, ники профилей, сайты."""
import re

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

PHONE_LABEL = r"(?<!\w)(?:телефон\w*|тел|т|факс|моб|сот)\.?[ \t]*(?:[:№][ \t]*)?"
PHONE_LOCAL_RE = re.compile(
    rf"{PHONE_LABEL}(\d{{1,3}}-\d{{2}}-\d{{2}}{PHONE_EXT}?)(?![\d-])",
    re.IGNORECASE,
)

# Код в скобках - телефон и без подписи: "(495) 123-45-67"
PHONE_NATIONAL_RE = re.compile(
    r"(?<![\d+])(?<![\d+][ \-])(?:"
    rf"\([3489]\d{{2}}\)[ \-]?{_digits_run(7)}"
    rf"|\([3489]\d{{3}}\)[ \-]?{_digits_run(6)}"
    rf"|\([3489]\d{{4}}\)[ \-]?{_digits_run(5)}"
    rf"){PHONE_EXT}?(?!\d)",
    re.IGNORECASE,
)
# только после "тел": "тел. 495 123-45-67"
PHONE_NATIONAL_LABELLED_RE = re.compile(
    rf"{PHONE_LABEL}([3489]\d{{2}}[ \-]?{_digits_run(7)}{PHONE_EXT}?)(?![\d-])",
    re.IGNORECASE,
)
# международный префикс "00" вместо "+": "00 44 20 7946 0958"
PHONE_IDD_RE = re.compile(r"(?<![\w+(])(?<!\d[ \-])00 ?(?=[1-9])")
EMAIL_RE = re.compile(r"[\w.%+\-]+@[\w.\-]+\.(?:[A-Za-zА-Яа-яЁё]{2,}|xn--[a-z0-9\-]+)")
TG_RE = re.compile(r"(?<![\w.\-@])@[A-Za-z][A-Za-z0-9_]{4,31}\b")

PROFILE_NICK_RE = re.compile(
    r"\b(?:github|gitlab|bitbucket|habr|behance|dribbble|kaggle|hh|linkedin)"
    r"\s*[:：]\s*([A-Za-z][\w.-]{2,38})", re.IGNORECASE)

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
