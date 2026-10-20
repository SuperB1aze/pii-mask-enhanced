"""Общие помощники тестов: маскировка без NER - по умолчанию или по набору."""
from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.engine.settings import Options, build_masker


def mask(text: str, preset: str | None = None) -> str:
    """Типы по умолчанию или список типов набора. Флаги набора (keep_positions,
    keep_balances) здесь не действуют - для них mask_with_preset."""
    types = presets.get(preset).types if preset else Masker().types
    return Masker(types=tuple(types), ner=False).mask(text)[0]


def mask_with_preset(text: str, preset: str, types: tuple[str, ...] = ()) -> str:
    """Как в CLI: набор вместе с его флагами; явный types сильнее набора."""
    masker, _ = build_masker(Options(preset=preset, types=types, ner=False), lambda: None)
    return masker.mask(text)[0]
