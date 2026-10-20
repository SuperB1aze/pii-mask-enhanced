"""Организации: правовая форма, кавычки, словарь пользователя."""
from __future__ import annotations

import re

from ...registry import sources
from .. import helpers
from .. import regulars as regs
from ..entity import Entity, from_match, text_key
from .spans import Span, before, inside


def _json_field(text: str, m: re.Match) -> bool:
    """Строка в кавычках - поле JSON: значение после '"ключ":' или сам ключ перед ':'."""
    return bool(regs.JSON_KEY_BEFORE_RE.search(before(text, m.start(), 45))
                or regs.JSON_KEY_AFTER_RE.match(text, m.end()))


def _stems(name: str) -> list[str]:
    """Отличительные слова названия."""
    words = re.findall(r"[А-ЯЁA-Z][\w-]{2,}", name)
    return [w for w in words if w.lower() not in helpers.ORG_GENERIC]


def _word_re(word: str) -> str:
    return rf"(?<!{helpers.WORD_CHAR}){re.escape(word)}(?!{helpers.WORD_CHAR})"


def _case_flags(word: str) -> int:
    # короткие - с учетом регистра: "ОКБ" да, "окб" нет
    return re.IGNORECASE if len(word) > 3 else 0


def orgs(text: str, org_names: tuple[str, ...]) -> list[Entity]:
    out: list[Entity] = []
    # Слова названий (stems) ищем по документу только от регулярок: ошибку NER
    # это размножило бы по всему тексту.
    named: list[Span] = []
    stems: set[str] = set()

    for m in regs.ORG_GENERIC_QUOTED_RE.finditer(text):
        out.append(Entity("ORG", m.group(1), m.start(1), m.end(1),
                          m.group(1).strip('«»"').lower()))

    for rx in (regs.ORG_QUOTED_RE, regs.ORG_TRAILING_FORM_RE):
        for m in rx.finditer(text):
            if inside(m.start(), m.end(), named):
                continue
            named.append(m.span())
            stems.update(_stems(m.group()))
            out.append(from_match("ORG", m))

    # последним: «Ромашка» внутри 'АО «Ромашка»' не выдаем второй раз
    for m in regs.ORG_QUOTED_NAME_RE.finditer(text):
        name = m.group(1)
        if _json_field(text, m) and regs.LATIN_VALUE_RE.fullmatch(name):
            continue
        if len(name) >= 3 and not inside(m.start(1), m.end(1), [(e.start, e.end) for e in out]):
            out.append(from_match("ORG", m, 1, key=str.lower))

    # словарь: сначала название целиком, чтобы "Ромашка Россия" была одной меткой
    for name in org_names:
        for m in re.finditer(_word_re(name), text, _case_flags(name)):
            if inside(m.start(), m.end(), named):
                continue
            named.append(m.span())
            out.append(from_match("ORG", m, key=lambda _: text_key(name), source=sources.DICT))

    # потом по словам - для названий, разорванных версткой
    for name in org_names:
        stems.update(_stems(name))
    stems |= set(helpers.prefixes(stems))
    for stem in stems:
        for m in re.finditer(_word_re(stem), text, _case_flags(stem)):
            if not inside(m.start(), m.end(), named):
                out.append(Entity("ORG", m.group(), m.start(), m.end(), stem.lower()))
    return out
