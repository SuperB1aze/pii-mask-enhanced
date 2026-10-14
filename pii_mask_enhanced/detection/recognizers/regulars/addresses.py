"""Адреса и место жительства."""
import re

from .. import helpers

ADDRESS_RE = re.compile(
    rf"(?:\d{{6}},?{helpers.WRAP})?{helpers.ADDR_REGION}{helpers.ADDR_DISTRICT}{helpers.ADDR_CITY}"
    rf"(?<![А-Яа-яЁё]){helpers.ADDR_HEAD},?{helpers.WRAP}{helpers.ADDR_TAIL}",
    re.IGNORECASE,
)
# "д.35, кв.47" без улицы: улицу по фамилии NER мог забрать как персону
ADDRESS_TAIL_RE = re.compile(
    rf"(?<![А-Яа-яЁё])д(?:ом)?\.?{helpers.WRAP}\d+[А-Яа-я]?[,\s]*кв\w*\.?{helpers.WRAP}\d+",
    re.IGNORECASE
)
# от индекса до конца строки или широкого отступа - адреса нестандартного вида
ADDRESS_RUN_RE = re.compile(
    r"(?<!\d)\d{6},[ \t]?(?:[^\n]{0,120}?)(?=\n|[ \t]{3,}|$)",
)

# индекс, за которым в 60 знаках идут регион или улица ("г." не признак - это и "год")
ADDRESS_INDEX_RE = re.compile(
    rf"(?<!\d)\d{{6}}(?=,[\s\S]{{0,60}}?"
    rf"(?:обл\.|область|край\b|респ\w*\.|округ|р-н|ул\.|улиц|пр-кт|просп|пер\.|шоссе))",
    re.IGNORECASE,
)

RESIDENCE_RE = re.compile(
    r"(?:проживает|проживание|город проживания|место жительства|город)\s*[:\-]\s*"
    r"([А-ЯЁ][а-яё]+(?:[ -][А-ЯЁ][а-яё]+){0,2})",
    re.IGNORECASE)
