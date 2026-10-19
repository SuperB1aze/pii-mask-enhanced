"""Подробности документа и карты: дата и орган выдачи, код подразделения, срок карты.

Привязаны к уже найденной сущности, поэтому применяются в engine/propagation
"""
import re

from ...registry.labelled_patterns import UNIT_CODE_LABEL
from .. import helpers

# дата выдачи с необязательным "г.": "12 марта 2015 г."
ISSUE_DATE_RE = re.compile(rf"{helpers.DATE}(?:[ \t]*г(?:од\w*|\.))?", re.IGNORECASE)
# хвост за паспортом или документом: "выдан ОВД района Арбат 12.03.2015, код подразделения 770-001"
ISSUE_AFTER_RE = re.compile(
    r"[ \t,.;]*(?:кем[ \t]+)?(?:выдан\w*|дата[ \t]+выдачи)[ \t:]*([^\n]{3,160})", re.IGNORECASE)
# подпись кода подразделения заканчивает орган; сам код - в registry/labelled_values
UNIT_CODE_LABEL_RE = re.compile(UNIT_CODE_LABEL, re.IGNORECASE)
# орган, перенесенный на следующую строку: "выдан Отделом УФМС России\nпо Тверской обл."
ISSUE_NEXT_LINE_RE = re.compile(r"\n[ \t]*(?=[а-яёa-z\d])[^\n]{1,120}")

# поля анкеты, если в тексте есть паспорт или документ; "кем выдан" - в registry/labelled_values
ISSUE_DATE_LABEL_RE = re.compile(rf"дата[ \t]+выдачи[ \t:]*\n?[ \t]*({ISSUE_DATE_RE.pattern})",
                                 re.IGNORECASE)
# "Выдан: ОВД района Арбат" отдельной строкой; двоеточие обязательно - "товар выдан" не поле
ISSUED_FIELD_RE = re.compile(r"(?<!\w)выдан\w*[ \t]*:[ \t]*\n?[ \t]*([^\n]{3,160})", re.IGNORECASE)
# орган выдачи кончается на запятой, широкой отбивке или границе колонки
ISSUER_END_RE = re.compile(r"[,;|]|[ \t]{3,}")

# срок действия карты: "12/27", "12/2027"
CARD_EXPIRY = r"(?<!\d)(?:0[1-9]|1[0-2])[ \t]?/[ \t]?(?:\d{4}|\d{2})(?!\d)"
_EXPIRY_WORD = (r"(?:срок\w*(?:[ \t]+действия)?(?:[ \t]+карты)?|действ\w*[ \t]+до|годна[ \t]+до"
                r"|valid[ \t]+(?:thru|through)|exp(?:iry|ires|\.)?(?:[ \t]+date)?)")
# сразу за картой подпись не обязательна: "4276 3800 1234 5679 12/27"
EXPIRY_AFTER_RE = re.compile(rf"[ \t,;]*(?:{_EXPIRY_WORD}[ \t:]*)?({CARD_EXPIRY})", re.IGNORECASE)
# где угодно - только у подписи и только "ММ/ГГ": "действует до 31.12.2026" - срок договора
EXPIRY_LABEL_RE = re.compile(rf"(?<!\w){_EXPIRY_WORD}[ \t:]*({CARD_EXPIRY})", re.IGNORECASE)
# Подпись, которая бывает только у карты
_EXPIRY_CARD_WORD = (r"(?:срок\w*[ \t]+действия[ \t]+карт\w*|карт\w*[ \t]+действ\w*[ \t]+до"
                     r"|valid[ \t]+(?:thru|through|until)|exp(?:iry|iration|ires|\.)?(?:[ \t]+date)?"
                     r"|(?-i:ММ/ГГ|MM/YY))")
EXPIRY_CARD_LABEL_RE = re.compile(rf"(?<!\w){_EXPIRY_CARD_WORD}[ \t:]*({CARD_EXPIRY})",
                                  re.IGNORECASE)
