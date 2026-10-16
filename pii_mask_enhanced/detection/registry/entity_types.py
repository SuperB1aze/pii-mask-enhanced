"""Реестр типов ПД: из него строятся наборы, приоритеты и подписи реквизитов."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..recognizers.validators import Validator


@dataclass(frozen=True)
class EntityType:
    name: str
    # меньше число - важнее при пересечении спанов
    priority: int
    # подписи реквизита: "ИНН 7701234567"
    labels: tuple[str, ...] = ()
    # проверка числа у подписи; не прошло - число остается общим REQ
    label_check: Callable[[str], bool] | None = None
    # номер, найденный по подписи, скрывается и в других местах текста
    spread: bool = False
    in_default: bool = False
    in_presets: bool = False
    # "personal" - данные человека и организации, "technical" - логи и сеть (IP, сессия).
    group: str = "personal"


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
    
    EntityType("SNILS", 4, labels=("СНИЛС",), label_check=Validator.snils_ok, spread=True, 
               in_default=True, in_presets=True),
    EntityType("PASSPORT", 6, in_default=True, in_presets=True),
    EntityType("IDDOC", 6, spread=True, in_default=True, in_presets=True),
    # VIN; важнее CERT: VIN из одних A-F и цифр - не сертификат
    EntityType("VEHICLE", 5, spread=True, in_default=True, in_presets=True),
    EntityType("INN", 6, labels=("ИНН",), spread=True, in_default=True, in_presets=True),
    EntityType("OGRN", 6, labels=("ОГРН", "ОГРНИП"), in_default=True, in_presets=True),
    EntityType("BIK", 5, labels=("БИК",), spread=True, in_default=True, in_presets=True),
    # только по подписи: 9 цифр без нее неотличимы от загранпаспорта или номера заказа
    EntityType("KPP", 6, labels=("КПП",), label_check=Validator.kpp_ok, spread=True,
               in_default=True, in_presets=True),
    EntityType("OKPO", 6, labels=("ОКПО",), label_check=Validator.okpo_ok, spread=True,
               in_default=True, in_presets=True),
    EntityType("ACCOUNT", 5, in_default=True, in_presets=True),
    EntityType("KADASTR_NUMBER", 6, spread=True, in_default=True, in_presets=True),
    EntityType("INVESTOR", 6, spread=True, in_default=True, in_presets=True),
    # Значения по подписи (registry/labelled_values)
    # идентификатор человека в чужой системе: ЕСИА, MDM, логин, полис, ЭЛН, таб. номер
    EntityType("PERSON_ID", 5, spread=True, in_default=True, in_presets=True),
    # PIN, CVV, пароль, кодовое слово
    EntityType("SECRET", 5, spread=True, in_default=True, in_presets=True),
    # пол, гражданство, семейное положение, возраст, кредитный рейтинг
    EntityType("PERSONAL", 9, in_default=True, in_presets=True),
    # кредитный рейтинг юрлица: шкалы агентств и внутренний рейтинг банка;
    EntityType("RATING", 7, in_default=True, in_presets=True),
    # должность и специальность по подписи; набор resume их оставляет (presets.keep_positions)
    EntityType("POSITION", 9, in_default=True, in_presets=True),
    # назначение платежа закрывается целиком
    EntityType("PAYMENT", 3, in_default=True, in_presets=True),
    EntityType("DOCREF", 6, in_presets=True),
    # дата рядом с ПД
    EntityType("DATE", 6, in_default=True, in_presets=True),
    # орган выдачи документа и код подразделения
    EntityType("ISSUER", 7, in_default=True, in_presets=True),

    EntityType("CERT", 9, in_presets=True),
    EntityType("UID", 7, in_default=True, in_presets=True),
    EntityType("REQ", 6, labels=("ОКТМО", "ОКВЭД"), in_default=True),

    EntityType("IP", 9, in_default=True, in_presets=True, group="technical"),
    EntityType("DEVICE", 5, in_default=True, in_presets=True, group="technical"),
    EntityType("SESSION", 8, in_default=True, in_presets=True, group="technical"),
    EntityType("USER_AGENT", 4, in_default=True, in_presets=True, group="technical"),
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
