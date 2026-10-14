"""Контакты: почта, телеграм, ники профилей, телефоны, сайты."""
from __future__ import annotations

import re

import phonenumbers

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity, digits
from .spans import Span, overlaps


def profile_nicks(text: str) -> list[Entity]:
    return [Entity("TG", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                   source=sources.PROFILE)
            for m in regs.PROFILE_NICK_RE.finditer(text)]


def emails(text: str) -> list[Entity]:
    # "https://ivanov:Qwerty123@host" - пароль и хост, а не почта
    creds = [m.span() for m in regs.URL_CREDS_RE.finditer(text)]
    return [Entity("EMAIL", m.group(), m.start(), m.end(), m.group().lower())
            for m in regs.EMAIL_RE.finditer(text)
            if not regs.FAKE_EMAIL_RE.match(m.group())
            and not any(overlaps(m.span(), c) for c in creds)]


def telegram(text: str) -> list[Entity]:
    return [Entity("TG", m.group(), m.start(), m.end(), m.group().lower())
            for m in regs.TG_RE.finditer(text)]


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0]
    return host.lower().removeprefix("www.")


def urls(text: str) -> list[Entity]:
    out: list[Entity] = []
    taken: list[Span] = []
    # у HINTED_DOMAIN_RE домен в группе 1; пересечения не дублируем ("https://сайт.рф")
    for rx in (regs.URL_SCHEME_RE, regs.BARE_DOMAIN_RE, regs.HINTED_DOMAIN_RE):
        for m in rx.finditer(text):
            g = 1 if rx.groups else 0
            url = m.group(g).rstrip(".,;:!?")
            start = m.start(g)
            # логин и пароль в адресе закрываются отдельно (finders/technical): адрес - с хоста
            creds = regs.URL_CREDS_RE.search(url) if rx is regs.URL_SCHEME_RE else None
            if creds:
                start += creds.end()
                url = url[creds.end():]
            span = (start, start + len(url))
            if _host(url) in helpers.STOP_HOSTS or any(overlaps(span, t) for t in taken):
                continue
            taken.append(span)
            out.append(Entity("URL", url, *span, url.lower()))
    return out


def _phone_key(number: str, ext: str = "") -> str:
    # "8 903..." и "+7 903..." - один номер и одна метка; добавочный отличает сотрудника
    if len(number) == 11 and number[0] == "8":
        number = "7" + number[1:]
    return number + (f"x{ext}" if ext else "")


def _split_ext(value: str) -> tuple[str, str]:
    m = re.search(regs.PHONE_EXT + "$", value, re.IGNORECASE)
    if not m:
        return digits(value), ""
    return digits(value[:m.start()]), digits(m.group())


def _international(text: str) -> list[Entity]:
    """Номера с "+" или "00" и кодом страны - по плану нумерации этой страны.

    Без региона библиотека берет только номера с кодом страны и сверяет длину и
    префикс: "+12 500 000 руб." - сумма, у +1 номер длиннее.
    """
    # "00 44 ..." библиотека не понимает: в копии для поиска "00" меняется на "+"
    shadow, starts = list(text), {}
    for m in regs.PHONE_IDD_RE.finditer(text):
        plus = m.end() - 1
        shadow[m.start():m.end()] = " " * (m.end() - m.start())
        shadow[plus] = "+"
        starts[plus] = m.start()
    out = []
    for m in phonenumbers.PhoneNumberMatcher("".join(shadow), None):
        num = m.number
        national = str(num.national_number)
        if num.country_code == 7 and national[:3] == regs.FAKE_PHONE_CODE:
            continue
        start = starts.get(m.start, m.start)
        out.append(Entity("PHONE", text[start:m.end], start, m.end,
                          _phone_key(f"{num.country_code}{national}", num.extension or "")))
    return out


def phones(text: str) -> list[Entity]:
    out = []
    for m in regs.PHONE_RE.finditer(text):
        number, ext = _split_ext(m.group())
        if number[1:4] != regs.FAKE_PHONE_CODE:
            out.append(Entity("PHONE", m.group(), m.start(), m.end(), _phone_key(number, ext)))
    for m in regs.PHONE_LOCAL_RE.finditer(text):
        number, ext = _split_ext(m.group(1))
        out.append(Entity("PHONE", m.group(1), m.start(1), m.end(1), _phone_key(number, ext)))
    return out + _international(text)
