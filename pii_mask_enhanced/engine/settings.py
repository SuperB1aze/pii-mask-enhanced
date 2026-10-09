"""Настройки маскировки -> Masker. Общие для CLI и API: один документ маскируется одинаково."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from ..detection import presets, profile
from ..detection.registry.entity_types import DEFAULT_TYPES
from .core import Masker


@dataclass(frozen=True)
class Options:
    preset: str | None = None
    # явный список заменяет список набора
    types: tuple[str, ...] | None = None
    ner: bool = True
    ner_types: tuple[str, ...] | None = None
    # флаги поверх набора только добавляют строгость
    ner_org_needs_form: bool = False
    ner_person_needs_fio: bool = False
    inn_needs_label: bool = False
    # снять требование правовой формы, если документ - резюме
    auto_profile: bool = False
    org_names: tuple[str, ...] = ()
    supported_names: tuple[str, ...] = ()


def type_names(values: Iterable[str] | None) -> tuple[str, ...] | None:
    return tuple(v.strip().upper() for v in values) if values else None


def build_masker(opts: Options, probe: Callable[[], str | None]) -> tuple[Masker, list[str]]:
    """Masker и пояснения к выбору набора. probe() - текст документа или None, зовется по нужде.

    ValueError - неизвестный набор или тип.
    """
    notes: list[str] = []
    preset = None
    if opts.preset:
        preset, why = presets.resolve(opts.preset, probe() if opts.preset == presets.AUTO else None)
        notes.append(why)

    needs_form = opts.ner_org_needs_form or bool(preset and preset.ner_org_needs_form)
    if needs_form and opts.auto_profile:
        text = probe()
        if text is None:
            notes.append("профиль: определить не удалось, остаюсь в строгом режиме")
        else:
            notes.append(profile.describe(text))
            needs_form = not profile.looks_like_resume(text)

    masker = Masker(
        types=opts.types or (preset.types if preset else DEFAULT_TYPES),
        ner=opts.ner,
        org_names=opts.org_names,
        ner_types=opts.ner_types,
        ner_org_needs_form=needs_form,
        ner_person_needs_fio=opts.ner_person_needs_fio or bool(preset and preset.ner_person_needs_fio),
        supported_names=opts.supported_names,
        inn_needs_label=opts.inn_needs_label or bool(preset and preset.inn_needs_label),
    )
    return masker, notes
