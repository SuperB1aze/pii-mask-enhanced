"""Контакты: почта, телеграм, ники профилей, телефоны, сайты."""
from __future__ import annotations

import re

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
    return [Entity("EMAIL", m.group(), m.start(), m.end(), m.group().lower())
            for m in regs.EMAIL_RE.finditer(text) if not regs.FAKE_EMAIL_RE.match(m.group())]


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
            span = (m.start(g), m.start(g) + len(url))
            if _host(url) in helpers.STOP_HOSTS or any(overlaps(span, t) for t in taken):
                continue
            taken.append(span)
            out.append(Entity("URL", url, *span, url.lower()))
    return out


def phones(text: str) -> list[Entity]:
    out = []
    for m in regs.PHONE_RE.finditer(text):
        d = digits(m.group())
        if d[1:4] != regs.FAKE_PHONE_CODE:
            out.append(Entity("PHONE", m.group(), m.start(), m.end(), d))
    return out
