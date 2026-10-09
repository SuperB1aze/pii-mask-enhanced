"""Именованные наборы: что считать персональными данными в документе"""
from __future__ import annotations

from dataclasses import dataclass

# REQ ("реквизит документа") исключен
TYPES = (
    "PERSON", "ORG", "INN", "OGRN", "KPP", "BIK", "ACCOUNT", "PHONE", "EMAIL",
    "ADDRESS", "DOCREF", "DATE", "CERT", "UID", "TG", "URL",
    "CARD", "SNILS", "PASSPORT", "OKPO",
)

# человека от NER принимаем, только если спан похож на ФИО
@dataclass(frozen=True)
class Preset:
    name: str
    title: str
    types: tuple[str, ...]
    ner_org_needs_form: bool
    ner_person_needs_fio: bool = True
    inn_needs_label: bool = True


_PRESETS = {
    "accounting": Preset(
        name="accounting",
        title="деловая бумага (счета, акты, выгрузки 1С)",
        types=TYPES,
        # Контрагент в бухгалтерском документе всегда с правовой формой, торговая марка - никогда
        ner_org_needs_form=True,
    ),
    "resume": Preset(
        name="resume",
        title="резюме и досье по опыту",
        types=TYPES,
        # то же требование на резюме работает наоборот: работодатели пишутся без ООО и без кавычек
        ner_org_needs_form=False,
    ),
}

AUTO = "auto"


def names() -> list[str]:
    return sorted(_PRESETS)


def get(name: str) -> Preset:
    try:
        return _PRESETS[name]
    except KeyError:
        raise ValueError(
            f"набор {name!r} не знаю; есть: {', '.join(names())} и "
            f"{AUTO} (выбрать по документу)") from None


def resolve(name: str, probe: str | None) -> tuple[Preset, str]:
    # набор и выбор пользователя
    if name != AUTO:
        chosen = get(name)
        return chosen, f"набор: {chosen.name} - {chosen.title}"

    from . import profile

    if probe is None:
        return _PRESETS["accounting"], (
            "набор: accounting - профиль определить не удалось, "
            "остаюсь в строгом режиме")
    chosen = _PRESETS["resume" if profile.looks_like_resume(probe) else "accounting"]
    return chosen, f"набор: {chosen.name} - {profile.describe(probe)}"
