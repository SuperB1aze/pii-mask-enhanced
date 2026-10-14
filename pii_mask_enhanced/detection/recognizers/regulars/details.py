"""Подробности документа и карты: дата и орган выдачи, код подразделения, срок карты.

Привязаны к уже найденной сущности, поэтому применяются в engine/propagation
"""
import re

from .. import helpers

# дата выдачи с необязательным "г.": "12 марта 2015 г."
ISSUE_DATE_RE = re.compile(rf"{helpers.DATE}(?:[ \t]*г(?:од\w*|\.))?", re.IGNORECASE)
# хвост за паспортом или документом: "выдан ОВД района Арбат 12.03.2015, код подразделения 770-001"
ISSUE_AFTER_RE = re.compile(
    r"[ \t,.;]*(?:кем[ \t]+)?(?:выдан\w*|дата[ \t]+выдачи)[ \t:]*([^\n]{3,160})", re.IGNORECASE)
# код подразделения
UNIT_CODE_RE = re.compile(r"код\w*[ \t]+подразделени\w*[ \t:№]*(\d{3}[ \t-]?\d{3})(?!\d)",
                          re.IGNORECASE)

ISSUE_DATE_LABEL_RE = re.compile(rf"дата[ \t]+выдачи[ \t:]*\n?[ \t]*({ISSUE_DATE_RE.pattern})",
                                 re.IGNORECASE)
ISSUER_LABEL_RE = re.compile(
    r"(?:кем[ \t]+выдан\w*|орган\w*,?[ \t]+выдавш\w+[ \t]+(?:документ|паспорт)\w*)[ \t:]*\n?[ \t]*"
    r"([^\n]{3,120})", re.IGNORECASE)
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
