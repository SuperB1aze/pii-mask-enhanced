"""Люди: ФИО капсом и с инициалами, дата и год рождения."""
import re

from ...registry.labelled_patterns import PERSON_TERMS
from .. import helpers

CAPS_FIO_RE = re.compile(
    rf"(?<![А-ЯЁ\w])(?:"
    # ФАМИЛИЯ ИМЯ ОТЧЕСТВО, фамилия может быть двойной
    rf"{helpers.CAPS_WORD}{helpers.FIO_SEP}(?:{helpers.CAPS_WORD}{helpers.FIO_SEP})?{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}{helpers.FIO_SEP}{helpers.CAPS_WORD}"
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"                        
    rf")(?![А-ЯЁ\w])"
)

CAPS_PATR_RE = re.compile(rf"(?<![А-ЯЁ\w])[А-ЯЁ]{{3,}}{helpers.PATR_TAIL}(?![А-ЯЁ\w])")

INITIALS_RE = re.compile(
    rf"(?<![А-ЯЁ\w]){helpers.SURNAME}[ \t]+[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.(?!\w)"
    rf"|(?<![А-ЯЁ\w])[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.[ \t]?{helpers.SURNAME}(?![А-ЯЁ\w])"
)

# только дата рождения; прочие даты не трогаем
BIRTH_DATE_RE = re.compile(
    r"(?:родил(?:ся|ась)|дата\s+рожд\w*\.?\s*[:\-]?|д\.?\s?р\.?\s*[:\-]?)\s*"
    rf"({helpers.DATE})",
    re.IGNORECASE)
# Дата смерти
DEATH_DATE_RE = re.compile(
    r"(?<!\w)(?:умер(?:ла)?|скончал(?:ся|ась)|погиб(?:ла)?|ум\.|"
    r"дат\w*\s+(?:смерти|кончины|гибели)\.?\s*[:\-]?)\s*"
    rf"(?:\s*в\s+)?({helpers.DATE})",
    re.IGNORECASE)
DEATH_YEAR_RE = re.compile(
    r"(?<!\w)(?:год\w*\s+(?:смерти|кончины|гибели)|умер(?:ла)?\s+в|скончал(?:ся|ась)\s+в"
    r"|погиб(?:ла)?\s+в)\s*[:\-]?\s*((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE)

# звание, степень, семейное положение, возраст - рядом с найденным ФИО (engine/propagation)
PERSON_TERMS_RE = re.compile(
    "|".join(rf"(?<!\w)(?:{t})(?!\w)" for t in PERSON_TERMS), re.IGNORECASE)
# сколько знаков до и после ФИО считается "рядом"; дальше строки окно не идет
PERSON_TERMS_WINDOW = 50

# год рождения: "1985 г.р.", "г.р. 1985"; точка обязательна, иначе "500 гр" - граммы
BIRTH_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[ \t]*г\.[ \t]?р\.?(?!\w)"
    r"|(?<!\w)г\.[ \t]?р\.[ \t]*((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE)
