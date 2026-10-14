"""Люди: ФИО капсом и с инициалами, дата и год рождения."""
import re

from .. import helpers

CAPS_FIO_RE = re.compile(
    rf"(?<![А-ЯЁ\w])(?:"
    # ФАМИЛИЯ ИМЯ ОТЧЕСТВО, фамилия может быть двойной
    rf"{helpers.CAPS_WORD}{helpers.FIO_SEP}(?:{helpers.CAPS_WORD}{helpers.FIO_SEP})?{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}{helpers.FIO_SEP}{helpers.CAPS_WORD}"  # ИМЯ ОТЧЕСТВО ФАМИЛИЯ
    rf"|{helpers.CAPS_WORD}{helpers.FIO_SEP}{helpers.CAPS_PATR}"                        # ИМЯ ОТЧЕСТВО
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
# год рождения: "1985 г.р.", "г.р. 1985"; точка обязательна, иначе "500 гр" - граммы
BIRTH_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[ \t]*г\.[ \t]?р\.?(?!\w)"
    r"|(?<!\w)г\.[ \t]?р\.[ \t]*((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE)
