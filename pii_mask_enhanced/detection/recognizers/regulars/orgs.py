"""Организации: правовая форма, кавычки, родовое слово."""
import re

from ...registry.legal_forms import ORG_FORM, TRAILING_FORM

# для проверки находок NER (Masker.ner_org_needs_form)
ORG_FORM_RE = re.compile(rf"\b{ORG_FORM}\b", re.IGNORECASE)

ORG_QUOTED_RE = re.compile(
    rf"{ORG_FORM}[ \t]*\n?[ \t]*[«\"][^»\"]{{2,80}}[»\"]", re.IGNORECASE
)

ORG_TRAILING_FORM_RE = re.compile(
    r"(?<![\w-])(?:[А-ЯЁA-Z][\w-]*[ \t]+){0,2}[А-ЯЁA-Z][\w-]*"
    rf"[ \t]*,[ \t]*{TRAILING_FORM}(?![\w-])(?![ \t]+[«\"А-ЯЁA-Z])"
)

# родовое слово + название в кавычках: 'ТРЦ "Ромашка"', 'БЦ "Полевой"'
_ORG_TYPE_GENERIC = (
    r"(?:ТРЦ|ТЦ|БЦ|ЖК|МФК|ТПУ|СРО|НИИ|КБ|завод|комбинат|фабрика|агентство"
    r"|холдинг|группа|управление|департамент)"
)
ORG_GENERIC_QUOTED_RE = re.compile(
    rf"(?<![\w-]){_ORG_TYPE_GENERIC}[ \t]+([«\"][^»\"\n]{{2,80}}[»\"])", re.IGNORECASE
)

ORG_QUOTED_NAME_RE = re.compile(
    r"[«\"“]((?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)(?:[ \t](?:[A-ZА-ЯЁ][\w.&+-]*|\d[\w.&+-]*)){0,2})[»\"”]")
