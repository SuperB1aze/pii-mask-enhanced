"""Распространение находок: повторы, словоформы и производные уже найденных сущностей.
"""
from __future__ import annotations

import re

from ..detection.ner.helpers import STOP_TERMS
from ..detection.ner.ner import NatashaNer, _is_stop_term
from ..detection.recognizers.recognizers import Entity
from ..detection.recognizers.regulars import DATE_AFTER_RE, ORG_FORM_RE

# окончания, которые срезаем перед поиском косвенных падежей
_VOWEL_END = "аеёиоуыэюяьй"

# Второе имя сразу за названием: "Ромашка (Romashka)", "Агентство ... (АСИ)", скрытое за скобкой
_ALIAS_RE = re.compile(r"[ \t]*\(([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9 .&-]{1,30})\)")


def _spans(known: list[Entity]) -> set[tuple[int, int]]:
    return {(e.start, e.end) for e in known}


def _stem(word: str) -> str:
    # склонение меняет окончание, поэтому ищем по основе без последней буквы
    return word[:-1] if word[-1].lower() in _VOWEL_END else word


def _free_matches(pattern: str, text: str, known: list[Entity]) -> list[re.Match]:
    # совпадения, спан которых еще не занят найденной сущностью
    taken = _spans(known)
    return [m for m in re.finditer(pattern, text) if (m.start(), m.end()) not in taken]


def org_core(value: str) -> str:
    # Ядро названия организации без правовой формы и без склонения. Составные названия не берем.
    core = ORG_FORM_RE.sub("", value).strip(" \t«»\"',.-")
    return core if core and " " not in core else ""


def repeats(text: str, values: set[str], known: list[Entity]) -> list[Entity]:
    # Повторные вхождения уже опознанных значений, которых нет среди находок.
    taken = _spans(known)
    by_value: dict[str, Entity] = {}
    for e in known:
        by_value.setdefault(e.text.strip(), e)
    out = []
    for value in values:
        if len(value) < 3:
            continue        # два знака встречаются в тексте случайно
        src = by_value[value]
        start = 0
        while True:
            at = text.find(value, start)
            if at < 0:
                break
            start = at + len(value)
            if (at, start) in taken:
                continue
            before = text[at - 1] if at else " "
            after = text[start] if start < len(text) else " "
            # Только целым токеном: иначе номер найдется внутри другого числа.
            # Исключение - "г" сразу за датой ("01.09.2026г.")
            tail_year = (src.type == "DATE" and after in "гГ"
                         and text[start + 1: start + 2] in {".", "", " ", "\n", ","})
            if before.isalnum() or (after.isalnum() and not tail_year):
                continue
            if tail_year:
                start += 2 if text[start + 1: start + 2] == "." else 1
                out.append(Entity(src.type, text[at:start], at, start, src.key,
                                  source="repeat"))
                continue
            out.append(Entity(src.type, value, at, start, src.key, source="repeat"))
    return out


def person_token_repeats(text: str, known: list[Entity]) -> list[Entity]:
    """Находит незамаскированные повторы слов из уже найденных ФИО.

    Например, отдельное "Иванов" после "Иванов Петр Сергеевич"
    """
    tokens = set()
    for ent in known:
        if ent.type != "PERSON":
            continue
        for tok in ent.text.replace(",", " ").split():
            tok = tok.strip(".,;:()\"'«»")
            if len(tok) >= 4 and tok[:1].isupper() and not _is_stop_term(tok):
                tokens.add(tok)
    out = []
    for tok in tokens:
        for m in _free_matches(rf"(?<![\w-]){re.escape(tok)}(?![\w-])", text, known):
            out.append(Entity("PERSON", tok, m.start(), m.end(),
                              tok.lower(), source="person-token"))
    return out


def dates_after_docrefs(text: str, known: list[Entity]) -> list[Entity]:
    # Дата сразу за номером документа
    out = []
    for ent in known:
        if ent.type != "DOCREF":
            continue
        m = DATE_AFTER_RE.match(text, ent.end)
        if m:
            out.append(Entity("DATE", m.group(1), m.start(1), m.end(1),
                              m.group(1).lower(), source="docdate"))
    return out


def bracket_aliases(text: str, known: list[Entity]) -> list[Entity]:
    out = []
    for src in known:
        if src.type != "ORG":
            continue
        m = _ALIAS_RE.match(text, src.end)
        if not m:
            continue
        alias = m.group(1).strip()
        # если больше трёх слов в скобках, то это пояснение
        if len(alias.split()) > 3:
            continue
        out.append(Entity("ORG", alias, m.start(1), m.end(1), src.key))
    return out


def org_case_repeats(text: str, known: list[Entity]) -> list[Entity]:
    # Подтвержденная организация в косвенном падеже.
    out = []
    for src in known:
        if src.type != "ORG" or len(src.text.strip()) < 5:
            continue
        value = org_core(src.text)
        if not value:
            continue
        stem = _stem(value)
        if len(stem) < 5:
            continue
        for m in _free_matches(re.escape(stem) + r"[а-яё]{0,3}\b", text, known):
            if m.start() and text[m.start() - 1].isalnum():
                continue
            out.append(Entity(src.type, m.group(), m.start(), m.end(), src.key))
    return out


def org_token_repeats(text: str, known: list[Entity], ner: NatashaNer) -> list[Entity]:
    # Слова подтвержденных названий, оставшиеся открытыми в других местах
    tokens: dict[str, Entity] = {}
    for src in known:
        if src.type != "ORG":
            continue
        # аббревиатуру капсом берем от трех знаков, обычное слово от пяти
        words = (re.findall(r"\b[А-ЯЁA-Z]{3,}\b", src.text)
                 + re.findall(r"[А-ЯЁA-Z][\w-]{4,}", src.text))
        for word in words:
            if word.lower() in STOP_TERMS or ner.known_common_word(word):
                continue
            tokens.setdefault(word, src)
    out = []
    for word, src in tokens.items():
        # аббревиатура не укорачивается
        stem = word if word.isupper() else _stem(word)
        if len(stem) < (3 if word.isupper() else 5):
            continue
        for m in _free_matches(re.escape(stem) + r"[а-яёa-z]{0,3}\b", text, known):
            if m.start() and (text[m.start() - 1].isalnum()
                              or text[m.start() - 1] in "-_"):
                continue
            out.append(Entity(src.type, m.group(), m.start(), m.end(), src.key))
    return out


def without_geo_persons(candidates: list[Entity], ner: NatashaNer) -> list[Entity]:
    # Убрать персоны, начатые географическим названием.
    # Пример: "России Б.Н. Ельцина" приняло за фамилию страну, проверка убирает метку
    out = []
    for ent in candidates:
        if ent.type == "PERSON":
            head = ent.text.strip().split()[0] if ent.text.strip() else ""
            if head and ner.is_geography(head):
                continue
        out.append(ent)
    return out
