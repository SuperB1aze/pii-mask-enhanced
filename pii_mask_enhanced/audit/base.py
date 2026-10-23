"""Третий слой: аудитор ищет ПД, оставшиеся в уже замаскированном тексте.

Аудитор только предлагает кандидатов - пары "подстрока, тип"
"""
from __future__ import annotations

import re
from typing import Iterable, Protocol

from ..detection.ner import morph
from ..detection.recognizers.entity import Entity
from ..detection.registry.entity_types import BY_NAME


class Auditor(Protocol):
    def available(self) -> bool:
        """Можно ли сейчас спрашивать; нет - маскировка с аудитом не выполняется."""

    def find(self, masked_text: str) -> Iterable[tuple[str, str]]:
        """Подстроки текста, похожие на оставшиеся ПД, и их тип из реестра."""


PROMPT = """Ты аудитор персональных данных. Ниже фрагмент рабочего текста, в котором персданные УЖЕ заменены на метки {{TYPE_N}}, фейковые телефоны +7 000 ... и адреса userN@example.com. Найди персональные данные, которые ОСТАЛИСЬ незамаскированными: имена и фамилии людей, названия компаний, телефоны, email, домашние адреса, ники и логины.

Правила:
- Верни JSON: {"entities": [{"text": "...", "type": "PERSON|ORG|PHONE|EMAIL|ADDRESS|NICKNAME|OTHER"}]}.
- В text копируй подстроку ИЗ ТЕКСТА ДОСЛОВНО, без изменений.
- Метки {{...}}, фейковые +7 000 и userN@example.com не включай - они уже замаскированы.
- Должности, роли, города, даты, деньги, технологии - НЕ персданные, не включай.
- Если ничего не осталось - верни {"entities": []}.

Текст:
"""

# ответ модели: {"entities": [{"text": ..., "type": ...}]}
SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "type": {"type": "string"}},
                "required": ["text", "type"],
            },
        }
    },
    "required": ["entities"],
}

_ALIASES = {"NICKNAME": "TG", "OTHER": "PERSON"}
_FALLBACK = "PERSON"


def chunks(text: str, size: int = 2500) -> list[str]:
    """Нарезать текст по абзацам на куски не больше size - под маленький контекст модели."""
    parts, buf, length = [], [], 0
    for para in text.split("\n\n"):
        if length + len(para) > size and buf:
            parts.append("\n\n".join(buf))
            buf, length = [], 0
        buf.append(para)
        length += len(para) + 2
    if buf:
        parts.append("\n\n".join(buf))
    return parts


def entity_type(name: str) -> str:
    name = name.strip().upper()
    name = _ALIASES.get(name, name)
    return name if name in BY_NAME else _FALLBACK


def plausible_candidate(etype: str, text: str) -> bool:
    """Отсев мусора аудитора теми же правилами, что и у NER"""
    if morph.is_stop_term(text):
        return False
    if etype != "PERSON":
        return True

    # Перечисление через запятую не считается человеком
    parts = [p.strip() for p in text.split(",")]
    if len(parts) > 1 and any(morph.is_stop_term(p) for p in parts):
        return False

    for word in re.findall(r"[^\W\d_]{2,}", text, re.UNICODE):
        known = morph.known(word.capitalize())
        # слова нет в словаре - может быть редким именем
        if not known or morph.has_name(known):
            return True
    return False


def to_entities(masked_text: str, candidates: Iterable[tuple[str, str]]) -> list[Entity]:
    """Кандидаты аудитора переходит в находки: каждое литеральное вхождение подстроки в текст."""
    found: list[Entity] = []
    for literal, etype in candidates:
        literal = str(literal).strip()
        if len(literal) < 2:
            continue
        etype = entity_type(str(etype))
        if not plausible_candidate(etype, literal):
            continue
        # только литеральные вхождения
        start = masked_text.find(literal)
        while start != -1:
            found.append(Entity(etype, literal, start, start + len(literal), literal.lower()))
            start = masked_text.find(literal, start + 1)
    return found
