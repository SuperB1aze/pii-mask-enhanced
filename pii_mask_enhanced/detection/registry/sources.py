"""Источник находки: кто ее нашел. Решает спор, когда один спан найден дважды."""
from __future__ import annotations

DICT = "dict"              # словарь организаций пользователя
REQUISITE = "requisite"    # число рядом с подписью ("ИНН 7701234567")
BARE = "bare"              # число без подписи, только по контрольной сумме
DOCREF = "docref"          # номер за словом "договор", "счет"...
DOCDATE = "docdate"        # дата за номером документа
REPEAT = "repeat"          # повтор уже найденного значения
PERSON_TOKEN = "person-token"
BIRTH = "birth"
RESIDENCE = "residence"
PROFILE = "profile"        # ник в строке "GitHub: nick"

_RANK = {DICT: 3, REQUISITE: 2, BARE: 0}


def rank(source: str) -> int:
    return _RANK.get(source, 1)
