"""Общие части для форматов Office Open XML (.docx, .xlsx): zip-архив с XML внутри."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as _sax_escape

from ..detection.recognizers.finders.numbers import id_doc_key
from ..detection.recognizers.regulars import ID_DOCS, LABELLED_VALUES
from ..detection.recognizers.validators import KPP_FORMAT
from ..detection.registry.entity_types import REQUISITE_WORD, requisite_type
from ..detection.registry.legal_forms import CELL_FORM

# Ссылки на символы: числовые (`&#10;` - перевод строки в ячейке) и пять именованных из XML.
_REF_RE = re.compile(r"&(?:#x([0-9A-Fa-f]+)|#(\d+)|(amp|lt|gt|quot|apos));")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}

# Текстовый узел <t> (в Word - <w:t>), в том числе пустой <t/>: он узел не открывает.
T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?(?<!/)>(.*?)</(?:\w+:)?t>|<(?:\w+:)?t(?:\s[^>]*)?/>", re.S)
# Любой непустой текстовый узел - чтобы заметить текст в частях, которые мы не разбираем.
ANY_T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?(?<!/)>([^<]+)</(?:\w+:)?t>", re.S)

# Свойства файла, где бывают имена: кто сохранил, о чем документ, чья организация.
_PROPERTY_FIELDS = {
    "docProps/core.xml": ("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject",
                          "dc:description", "cp:keywords", "cp:category"),
    "docProps/app.xml": ("Company", "Manager"),
}

# Правовые формы: по ним видно, кто в документе контрагент.
_LEGAL_FORM = re.compile(rf"\b{CELL_FORM}\b", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[^\w\-]+")

# Подпись реквизита отдельной ячейкой: число рядом с ней считается реквизитом.
REQ_LABEL_RE = re.compile(rf"^\s*({REQUISITE_WORD})\s*:?\s*$", re.IGNORECASE)
# число у подписи реквизита; счет с группами разбирает справочник значений по подписи
DIGITS_CELL_RE = re.compile(rf"^(?:\d{{5,20}}|{KPP_FORMAT})$")


def unescape(text: str) -> str:
    """Разобрать ссылки на символы за один проход.

    В два прохода `&amp;#10;` сначала стал бы `&#10;`, а потом ошибочно переводом строки.
    """
    def one(m: re.Match) -> str:
        if m.group(1):
            return chr(int(m.group(1), 16))
        if m.group(2):
            return chr(int(m.group(2)))
        return _NAMED[m.group(3)]

    return _REF_RE.sub(one, text)


def escape(text: str, attr: bool = False) -> str:
    """Экранировать текст узла. `\\r` пишем ссылкой, иначе парсер заменит его на `\\n`.
    Если текст атрибута, то экранируем кавычки и табуляцию.
    """
    if attr:
        return _sax_escape(text, {'"': "&quot;", "\n": "&#10;", "\t": "&#9;", "\r": "&#13;"})
    return _sax_escape(text).replace("\r", "&#13;")


def tag(name: str) -> bytes:
    """Тег с необязательным префиксом пространства имен: `<si>` и `<x:si>`; пустой `<si/>` не в счет."""
    return rf"<(?:\w+:)?{name}(?:\s[^>]*)?(?<!/)>(.*?)</(?:\w+:)?{name}>".encode()


def runs_text(body: bytes) -> str:
    """Текст контейнера: все его узлы <t> подряд."""
    runs = [m.group(1) or b"" for m in T_RE.finditer(body)]
    return unescape(b"".join(runs).decode("utf-8"))


def unknown_text_parts(z: zipfile.ZipFile, known: set[str], no_text: re.Pattern) -> list[str]:
    """Части с текстом, которые мы не разбираем: диаграммы, надписи, чужое."""
    bad = []
    for n in z.namelist():
        if n in known or no_text.match(n) or not n.endswith(".xml"):
            continue
        if any(m.group(1).strip() for m in ANY_T_RE.finditer(z.read(n))):
            bad.append(n)
    return sorted(bad)


def strip_properties(name: str, blob: bytes) -> bytes:
    """Вычистить из свойств файла поля, где бывают имена."""
    for field in _PROPERTY_FIELDS.get(name, ()):
        blob = re.sub(rf"<{field}(\s[^>]*)?>[^<]*</{field}>".encode(),
                      rf"<{field}\1></{field}>".encode(), blob)
    return blob


def clear_attrs(blob: bytes, names: tuple[str, ...]) -> bytes:
    """Опустошить значения атрибутов с этими именами, с любым префиксом."""
    alts = "|".join(names)
    rx = rf"""(\s(?:\w+:)?(?:{alts})=)(?:"[^"]*"|'[^']*')""".encode()
    return re.sub(rx, rb'\1""', blob)


def write_copy(zin: zipfile.ZipFile, dst: str | Path, done: dict[str, bytes]) -> None:
    """Записать копию архива: части из `done` - новые, прочие - как были, свойства - без имен."""
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = done.get(info.filename) or zin.read(info.filename)
            zout.writestr(info, strip_properties(info.filename, blob))


def counterparty_words(values: list[str]) -> frozenset[str]:
    """Слова из значений с правовой формой: документ сам объявляет контрагентов."""
    names: set[str] = set()
    for value in values:
        if not _LEGAL_FORM.search(value):
            continue
        for word in _WORD_SPLIT.split(value):
            if len(word) >= 3 and not word.isdigit() and not _LEGAL_FORM.fullmatch(word):
                names.add(word.lower())
    return frozenset(names)


def cell_label(label: str, value: str) -> tuple[str, str] | None:
    """Тип и ключ значения по подписи в соседней ячейке: "Р/с" | "40817..." -> ACCOUNT.

    Ключ строит та же ветка, что опознала значение, - как у находки в тексте: иначе
    одно значение в ячейке и в строке получило бы две метки.
    """
    value = value.strip()
    # "Р/с" | "40817...", "ЕСИА ID" | "1000123456", "Пол" | "жен."
    for lv in LABELLED_VALUES:
        if lv.cell_label.match(label) and lv.cell_value.match(value):
            return lv.type, lv.key(value)
    # "Военный билет" | "АБ 1234567": подпись - название документа, ячейка - его номер
    if any(doc.context and doc.context.search(label) and doc.number.fullmatch(value)
           for doc in ID_DOCS):
        return "IDDOC", id_doc_key(value)
    m = REQ_LABEL_RE.match(label)
    if m and DIGITS_CELL_RE.match(value):
        return requisite_type(m.group(1), value), value
    return None


def cell_label_type(label: str, value: str) -> str | None:
    """Только тип из cell_label."""
    hit = cell_label(label, value)
    return hit[0] if hit else None


def numbers_after_labels(values: list[str]) -> dict[str, tuple[str, str]]:
    """Значения сразу за подписью: тип и ключ. Ячейки таблицы Word идут подряд по строке."""
    out: dict[str, tuple[str, str]] = {}
    prev = ""
    for value in values:
        if not value.strip():
            continue
        hit = cell_label(prev, value)
        if hit:
            out[value.strip()] = hit
        prev = value
    return out


def mask_values(values: list[str], masker, mapping: dict | None) -> tuple[list[str], dict]:
    """Замаскировать значения по порядку; пустые и пробельные - как есть."""
    masked = []
    for value in values:
        if not value.strip():
            masked.append(value)
            continue
        out, mapping = masker.mask(value, mapping)
        masked.append(out)
    return masked, mapping
