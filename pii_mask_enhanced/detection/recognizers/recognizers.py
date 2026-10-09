"""Форматные ПД РФ: regex + контрольные суммы."""
from __future__ import annotations

from pathlib import Path

from .entity import Entity
from .finders import addresses, contacts, numbers, orgs, persons, requisites, spans


def find_format_entities(text: str, org_names: tuple[str, ...] = ()) -> list[Entity]:
    """Найти форматные ПД. org_names - словарь организаций (load_org_dict)."""
    # Порядок важен: при равном приоритете, длине и начале спана побеждает найденное раньше.
    found = [
        *contacts.profile_nicks(text),
        *persons.birth_dates(text),
        *addresses.residences(text),
        *contacts.emails(text),
        *contacts.telegram(text),
        *contacts.urls(text),
        *contacts.phones(text),
        *numbers.cards(text),
        *numbers.snils(text),
        *numbers.inns(text),
        *numbers.certs(text),
        *requisites.docrefs(text),
        *requisites.paired(text),
        *requisites.labelled(text),
        *requisites.accounts(text),
        *addresses.addresses(text),
        *requisites.doc_numbers(text),
        *orgs.orgs(text, org_names),
        *numbers.ogrns(text),
        *numbers.uids(text),
        *numbers.passports(text),
        *persons.persons(text),
    ]
    return spans.best_by_source(found)


def load_org_dict(path) -> tuple[str, ...]:
    """Словарь названий организаций: по одному на строку, '#' - комментарий."""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"словарь организаций не найден: {p}")
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return tuple(names)
