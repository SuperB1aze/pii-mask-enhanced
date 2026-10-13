"""Распространение находок: повторы, словоформы и производные уже найденных сущностей.
"""
from __future__ import annotations

import re

from ..detection.ner import morph
from ..detection.ner.helpers import STOP_TERMS
from ..detection.recognizers import regulars as regs
from ..detection.recognizers.entity import Entity, digits
from ..detection.recognizers.regulars import DATE_AFTER_RE, ORG_FORM_RE
from ..detection.registry import sources

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
                                  source=sources.REPEAT))
                continue
            out.append(Entity(src.type, value, at, start, src.key, source=sources.REPEAT))
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
            if len(tok) >= 4 and tok[:1].isupper() and not morph.is_stop_term(tok):
                tokens.add(tok)
    out = []
    for tok in tokens:
        for m in _free_matches(rf"(?<![\w-]){re.escape(tok)}(?![\w-])", text, known):
            out.append(Entity("PERSON", tok, m.start(), m.end(),
                              tok.lower(), source=sources.PERSON_TOKEN))
    return out


# --- Подробности рядом с найденным: дата договора, дата и орган выдачи, срок карты ---

def _issuer(text: str, start: int, end: int) -> Entity | None:
    # орган выдачи - до запятой или отбивки; без единой прописной это не название органа
    seg = text[start:end]
    cut = regs.ISSUER_END_RE.search(seg)
    if cut:
        seg = seg[:cut.start()]
    name = seg.strip(" \t.:-")
    if len(name) < 3 or not any(c.isupper() for c in name):
        return None
    at = start + seg.index(name)
    return Entity("ISSUER", name, at, at + len(name), " ".join(name.lower().split()),
                  source=sources.ISSUE)


def _after_docref(text: str, ent: Entity) -> list[Entity]:
    m = DATE_AFTER_RE.match(text, ent.end)
    if not m:
        return []
    return [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                   source=sources.DOCDATE)]


def _after_document(text: str, ent: Entity) -> list[Entity]:
    # "выдан ОВД района Арбат 12.03.2015" и "выдан 12.03.2015 ОУФМС России по г. Москве"
    m = regs.ISSUE_AFTER_RE.match(text, ent.end)
    if not m:
        return []
    base, tail = m.start(1), m.group(1)
    date = regs.ISSUE_DATE_RE.search(tail)
    code = regs.UNIT_CODE_RE.search(tail)
    out = []
    if date:
        out.append(Entity("DATE", date.group(), base + date.start(), base + date.end(),
                          date.group().lower(), source=sources.ISSUE))
    # орган - до даты, а если там пусто, то после нее; код подразделения его заканчивает
    stops = [x.start() for x in (date, code) if x]
    issuer = _issuer(text, base, base + min(stops, default=len(tail)))
    if issuer is None and date:
        end = code.start() if code and code.start() > date.end() else len(tail)
        issuer = _issuer(text, base + date.end(), base + end)
    if issuer:
        out.append(issuer)
    return out


def _after_card(text: str, ent: Entity) -> list[Entity]:
    m = regs.EXPIRY_AFTER_RE.match(text, ent.end)
    if not m:
        return []
    return [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1), source=sources.EXPIRY)]


# тип якоря -> что искать сразу за ним
_AFTER = {
    "DOCREF": _after_docref,
    "PASSPORT": _after_document,
    "IDDOC": _after_document,
    "CARD": _after_card,
}


def _labelled_details(text: str, known: list[Entity]) -> list[Entity]:
    """Те же подробности по подписи где угодно в тексте - если якорь в тексте есть.

    В анкете "Дата выдачи" и "Кем выдан" - отдельные поля, не рядом с номером.
    Код подразделения узнается по подписи и без паспорта.
    """
    anchors = {e.type for e in known}
    out = [Entity("ISSUER", m.group(1), m.start(1), m.end(1), digits(m.group(1)),
                  source=sources.ISSUE)
           for m in regs.UNIT_CODE_RE.finditer(text)]
    if anchors & {"PASSPORT", "IDDOC"}:
        out += [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                       source=sources.ISSUE)
                for m in regs.ISSUE_DATE_LABEL_RE.finditer(text)]
        for m in regs.ISSUER_LABEL_RE.finditer(text):
            issuer = _issuer(text, m.start(1), m.end(1))
            if issuer:
                out.append(issuer)
    if "CARD" in anchors:
        out += [Entity("DATE", m.group(1), m.start(1), m.end(1), m.group(1),
                       source=sources.EXPIRY)
                for m in regs.EXPIRY_LABEL_RE.finditer(text)]
    return out


def linked_details(text: str, known: list[Entity]) -> list[Entity]:
    """Подробности, которые ПД только рядом с найденной сущностью.

    Дата сама по себе не ПД, а дата договора, дата выдачи паспорта и срок карты - ПД.
    Поэтому они ищутся не распознавателями, а здесь: от уже найденного номера.
    """
    out = []
    for ent in known:
        handler = _AFTER.get(ent.type)
        if handler:
            out += handler(text, ent)
    return out + _labelled_details(text, known)


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


def org_token_repeats(text: str, known: list[Entity]) -> list[Entity]:
    # Слова подтвержденных названий, оставшиеся открытыми в других местах
    tokens: dict[str, Entity] = {}
    for src in known:
        if src.type != "ORG":
            continue
        # аббревиатуру капсом берем от трех знаков, обычное слово от пяти
        words = (re.findall(r"\b[А-ЯЁA-Z]{3,}\b", src.text)
                 + re.findall(r"[А-ЯЁA-Z][\w-]{4,}", src.text))
        for word in words:
            if word.lower() in STOP_TERMS or morph.is_known_common(word):
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


def without_geo_persons(candidates: list[Entity]) -> list[Entity]:
    # Убрать персоны, начатые географическим названием.
    # Пример: "России Б.Н. Ельцина" приняло за фамилию страну, проверка убирает метку
    out = []
    for ent in candidates:
        if ent.type == "PERSON":
            head = ent.text.strip().split()[0] if ent.text.strip() else ""
            if head and morph.is_geography(head):
                continue
        out.append(ent)
    return out
