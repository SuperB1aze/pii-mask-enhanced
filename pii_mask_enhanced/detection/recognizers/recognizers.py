"""Форматные ПД РФ: regex + контрольные суммы."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .entity import Entity
from .finders import (addresses, contacts, numbers, orgs, persons, requisites, spans,
                      special, technical)


# Порядок обхода
_FINDERS: tuple[Callable[..., list[Entity]], ...] = (
    contacts.profile_nicks, persons.birth_dates, special.criminal, special.health,
    special.clearance, special.shares, addresses.residences, contacts.emails, contacts.telegram,
    contacts.urls, contacts.phones, technical.user_agents, technical.ips, technical.internal_hosts,
    technical.devices, technical.sessions, technical.behavior, technical.credentials,
    technical.secrets, numbers.card_tracks, numbers.cards, numbers.masked_cards, numbers.vins,
    numbers.plates, numbers.snils, numbers.inns, numbers.accounts_bare, numbers.biks,
    numbers.certs, numbers.kadastr_numbers, requisites.docrefs, requisites.client_docnums,
    requisites.paired, requisites.labelled, requisites.labelled_values, requisites.incomes,
    requisites.moex_codes, addresses.addresses, addresses.coordinates, requisites.gov_docs,
    requisites.doc_numbers, orgs.orgs, numbers.ogrns, numbers.uids, numbers.id_documents,
    numbers.passports, persons.persons,
)


def find_format_entities(text: str, org_names: tuple[str, ...] = ()) -> list[Entity]:
    """Найти форматные ПД. org_names - словарь организаций (load_org_dict)."""
    found = [ent for find in _FINDERS
             for ent in (find(text, org_names) if find is orgs.orgs else find(text))]
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
