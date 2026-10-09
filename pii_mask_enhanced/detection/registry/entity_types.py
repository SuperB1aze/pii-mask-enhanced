"""Реестр типов ПД: из него строятся наборы, приоритеты и подписи реквизитов."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..recognizers.validators import Validator


@dataclass(frozen=True)
class EntityType:
    name: str
    # меньше - важнее при пересечении спанов
    priority: int
    # подписи реквизита: "ИНН 7701234567"
    labels: tuple[str, ...] = ()
    # проверка числа у подписи; не прошло - число остается общим REQ
    label_check: Callable[[str], bool] | None = None
    # номер, найденный по подписи, скрывается и в других местах текста
    spread: bool = False
    in_default: bool = False
    in_presets: bool = False


TYPES = (
    EntityType("PERSON", 9, in_default=True, in_presets=True),
    EntityType("ORG", 10, in_default=True, in_presets=True),
    EntityType("LOC", 11),
    EntityType("PHONE", 5, in_default=True, in_presets=True),
    EntityType("EMAIL", 1, in_default=True, in_presets=True),
    EntityType("TG", 2, in_default=True, in_presets=True),
    EntityType("URL", 8, in_default=True, in_presets=True),
    EntityType("ADDRESS", 8, in_default=True, in_presets=True),
    EntityType("CARD", 3, in_default=True, in_presets=True),
    EntityType("SNILS", 4, in_default=True, in_presets=True),
    EntityType("PASSPORT", 7, in_default=True, in_presets=True),
    EntityType("INN", 6, labels=("ИНН",), spread=True, in_default=True, in_presets=True),
    EntityType("OGRN", 6, labels=("ОГРН", "ОГРНИП"), in_default=True, in_presets=True),
    EntityType("KPP", 6, labels=("КПП",), spread=True, in_presets=True),
    EntityType("BIK", 6, labels=("БИК",), in_presets=True),
    EntityType("OKPO", 6, labels=("ОКПО",), label_check=Validator.okpo_ok, spread=True,
               in_default=True, in_presets=True),
    EntityType("ACCOUNT", 6, in_presets=True),
    EntityType("DOCREF", 6, in_presets=True),
    EntityType("DATE", 6, in_presets=True),
    EntityType("CERT", 6, in_presets=True),
    EntityType("UID", 7, in_default=True, in_presets=True),
    # в наборах выключен: в КУДиР это номер первичного документа ("№ 4")
    EntityType("REQ", 6, labels=("ОКТМО", "ОКВЭД"), in_default=True),
)

BY_NAME = {t.name: t for t in TYPES}

DEFAULT_TYPES = tuple(t.name for t in TYPES if t.in_default)
PRESET_TYPES = tuple(t.name for t in TYPES if t.in_presets)
PRIORITY = {t.name: t.priority for t in TYPES}
SPREAD_TYPES = frozenset(t.name for t in TYPES if t.spread)

# подпись в нижнем регистре -> тип
REQUISITE_LABELS = {label.lower(): t.name for t in TYPES for label in t.labels}
# длинные первыми: "ОГРНИП" раньше "ОГРН"
REQUISITE_WORD = "(?:" + "|".join(sorted((label for t in TYPES for label in t.labels),
                                         key=len, reverse=True)) + ")"


def requisite_type(label: str, num: str) -> str:
    etype = BY_NAME[REQUISITE_LABELS.get(label.strip().lower(), "REQ")]
    if etype.label_check and not etype.label_check(num):
        return "REQ"
    return etype.name


def check_types(names) -> None:
    unknown = sorted(set(names) - BY_NAME.keys())
    if unknown:
        raise ValueError(f"неизвестные типы: {', '.join(unknown)}; "
                         f"есть: {', '.join(BY_NAME)}")
