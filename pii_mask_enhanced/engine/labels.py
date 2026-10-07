"""Метки и mapping: выдача метки сущности и обратная замена (unmask).

mapping - {"version": 1, "labels": {placeholder: {"type", "original", "key", "n", "aliases"?}}}.
Форматные типы PHONE/EMAIL получают формат-сохраняющие фейки, остальные - {{TYPE_N}}.
"""
from __future__ import annotations

import re

from ..detection.recognizers.recognizers import Entity, digits
from ..detection.recognizers.regulars import FAKE_EMAIL_RE

LABEL_RE = re.compile(r"\{\{([A-Z]+)_(\d+)\}\}")
PHONE_SCAN_RE = re.compile(r"\+?[78][\d \-()]{9,18}\d")
FAKE_EMAIL_SCAN_RE = re.compile(r"user\d+@example\.com", re.IGNORECASE)

UNKNOWN = "[неизвестное значение]"


def make_placeholder(etype: str, n: int) -> str:
    if etype == "PHONE":
        return f"+7 000 000-{n // 100:02d}-{n % 100:02d}"
    if etype == "EMAIL":
        return f"user{n}@example.com"
    return f"{{{{{etype}_{n}}}}}"


def is_own_artifact(s: str) -> bool:
    # метка или фейк, которые выдали мы сами
    s = s.strip()
    if LABEL_RE.search(s):
        return True
    if FAKE_EMAIL_RE.match(s):
        return True
    d = digits(s)
    return len(d) == 11 and d[1:4] == "000"


def assign_label(labels: dict, ent: Entity) -> str:
    for placeholder, rec in labels.items():
        if rec["type"] == ent.type and (
            rec["key"] == ent.key or ent.key in rec.get("aliases", [])
        ):
            return placeholder

    # одиночное имя линкуем к единственному полному ФИО с этим токеном
    if ent.type == "PERSON" and " " not in ent.key:
        hosts = [
            (placeholder, rec)
            for placeholder, rec in labels.items()
            if rec["type"] == "PERSON" and " " in rec["key"] and ent.key in rec["key"].split()
        ]
        if len(hosts) == 1:
            placeholder, rec = hosts[0]
            rec.setdefault("aliases", []).append(ent.key)
            return placeholder

    n = 1 + max(
        (rec["n"] for rec in labels.values() if rec["type"] == ent.type), default=0
    )
    placeholder = make_placeholder(ent.type, n)
    original = ent.text
    # лемму подставляем только для явно косвенной формы
    if ent.type == "PERSON" and ent.oblique:
        original = ent.key.title()  # восстанавливается именительный падеж
    labels[placeholder] = {"type": ent.type, "original": original, "key": ent.key, "n": n}
    return placeholder


def unmask(text: str, mapping: dict) -> str:
    labels: dict = mapping.get("labels", {})

    def sub_label(m: re.Match) -> str:
        rec = labels.get(m.group(0))
        return rec["original"] if rec else UNKNOWN

    text = LABEL_RE.sub(sub_label, text)

    phone_by_digits = {
        digits(placeholder): rec["original"]
        for placeholder, rec in labels.items()
        if rec["type"] == "PHONE"
    }

    def sub_phone(m: re.Match) -> str:
        d = digits(m.group(0))
        if d in phone_by_digits:
            return phone_by_digits[d]
        if d[1:4] == "000":  # выдуманный моделью номер из фейкового диапазона
            return UNKNOWN
        return m.group(0)

    text = PHONE_SCAN_RE.sub(sub_phone, text)

    def sub_email(m: re.Match) -> str:
        rec = labels.get(m.group(0).lower())
        return rec["original"] if rec else UNKNOWN

    return FAKE_EMAIL_SCAN_RE.sub(sub_email, text)
