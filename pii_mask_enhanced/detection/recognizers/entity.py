"""Находка распознавателя."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Entity:
    type: str
    text: str
    start: int
    end: int
    key: str  # ключ консистентности: одинаковый key -> одна метка
    # слово не в именительном падеже ("Ивану")
    oblique: bool = False
    # кто нашел (registry/sources); решает спор при пересечениях
    source: str = ""


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())
