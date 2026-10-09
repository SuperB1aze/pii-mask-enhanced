"""Маскировка книги Excel (.xlsx) без внешних зависимостей."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from .office_xml import (DIGITS_ONLY_RE, REQ_LABEL_RE, T_RE, clear_attrs, counterparty_words,
                         escape, mask_values, runs_text, tag, unknown_text_parts, unescape,
                         write_copy)

# Контейнеры текстовых узлов <t>: ячейка общей таблицы, ячейка листа, комментарий.
# Автор комментария хранится отдельным узлом, без <t>.
_ITEM_RE = {k: re.compile(tag(k), re.S) for k in ("si", "is", "text", "author")}
# Колонтитул печати листа и текст цепочки примечаний - строкой, без <t>.
_ITEM_RE["hf"] = re.compile(tag("(?:odd|even|first)(?:Header|Footer)"), re.S)
_ITEM_RE["tc"] = _ITEM_RE["text"]
_PLAIN = {"author", "hf", "tc"}

# Коды колонтитула: &L &C &R (часть), &P &N &D (поля), &"Шрифт,Жирный", &12, &KFF0000.
# Маскируем только текст между ними: "&LСоколова" распознаватель как имя не увидит.
_HF_CODE_RE = re.compile(r'(&(?:"[^"]*"|\d+|K[0-9A-Fa-f]{6}|K\d\d[+-]\d{3}|.))', re.S)

# Части, где мы умеем читать текст, в порядке обхода. Лист не обязан называться sheet1.xml.
_PART_KINDS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^xl/sharedStrings\.xml$"), "si"),
    (re.compile(r"^xl/worksheets/[^/]+\.xml$"), "is"),
    (re.compile(r"^xl/worksheets/[^/]+\.xml$"), "hf"),
    (re.compile(r"^xl/comments\d*\.xml$"), "author"),
    (re.compile(r"^xl/comments\d*\.xml$"), "text"),
    (re.compile(r"^xl/threadedComments/[^/]+\.xml$"), "tc"),
)

# Авторы примечаний: имя и учетная запись.
_PERSONS = re.compile(r"^xl/persons/[^/]+\.xml$")
_PERSON_ATTRS = ("displayName", "userId")

# Части без пользовательского текста: разметка, оформление, связи.
_NO_TEXT = re.compile(
    r"^(\[Content_Types\]\.xml|_rels/|xl/_rels/|xl/styles\.xml|xl/theme/|"
    r"xl/workbook\.xml|xl/calcChain\.xml|xl/sharedStrings\.xml|"
    r"xl/worksheets/|xl/comments\d*\.xml|docProps/)"
)


def _sort_key(name: str) -> tuple:
    """sheet2 раньше sheet10; прочие имена - по алфавиту."""
    m = re.search(r"(\d+)\.xml$", name)
    return (0, int(m.group(1)), "") if m else (1, 0, name)


def _parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Части с текстом и вид контейнера, в устойчивом порядке обхода."""
    out: list[tuple[str, str]] = []
    for rx, kind in _PART_KINDS:
        names = sorted((n for n in z.namelist() if rx.match(n)), key=_sort_key)
        out.extend((n, kind) for n in names)
    return out


def _item_value(body: bytes, kind: str) -> str:
    if kind in _PLAIN:
        return unescape(body.decode("utf-8"))
    return runs_text(body)


def _item_values(body: bytes, kind: str) -> list[str]:
    """Значения контейнера для маскировки: у колонтитула - куски текста между кодами."""
    value = _item_value(body, kind)
    return _HF_CODE_RE.split(value)[0::2] if kind == "hf" else [value]


def cell_texts(path: str | Path) -> list[str]:
    """Весь текст книги, который мы умеем обезличивать, в устойчивом порядке."""
    values: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name, kind in _parts(z):
            for item in _ITEM_RE[kind].finditer(z.read(name)):
                values.extend(_item_values(item.group(1), kind))
    return values


def _rewrite_part(blob: bytes, kind: str, values: list[str], cursor: int) -> tuple[bytes, int]:
    def one(match: re.Match) -> bytes:
        nonlocal cursor
        body = match.group(1)
        old = _item_value(body, kind)
        if kind == "hf":
            pieces = _HF_CODE_RE.split(old)
            n = len(pieces[0::2])
            pieces[0::2], cursor = values[cursor:cursor + n], cursor + n
            new = "".join(pieces)
        else:
            new, cursor = values[cursor], cursor + 1
        whole = match.group(0)
        head = whole[:match.start(1) - match.start(0)]
        tail = whole[match.end(1) - match.start(0):]

        if old == new:
            return whole      # значение не изменилось - оформление цело

        payload = escape(new).encode("utf-8")
        if kind in _PLAIN:
            return head + payload + tail

        first = True

        def run(_t: re.Match) -> bytes:
            nonlocal first
            if not first:
                return b"<t/>"      # весь текст ячейки пишем в первый узел
            first = False
            return b'<t xml:space="preserve">' + payload + b"</t>"

        return head + T_RE.sub(run, body) + tail

    return _ITEM_RE[kind].sub(one, blob), cursor


def rewrite(src: str | Path, dst: str | Path, values: list[str]) -> None:
    """Собрать копию книги с подставленными значениями.

    `values` - результат `cell_texts` для этой же книги, в том же порядке.
    """
    src, dst = Path(src), Path(dst)
    if dst.exists() and src.samefile(dst):
        # запись в тот же файл стерла бы исходник до чтения
        raise ValueError("нельзя писать поверх исходной книги - укажи другой файл")
    have = cell_texts(src)
    if len(values) != len(have):
        raise ValueError(
            f"значений {len(values)}, а текстовых узлов в книге {len(have)} - "
            "подстановка сдвинулась бы по всей книге")

    cursor = 0
    with zipfile.ZipFile(src) as zin:
        # Правим в порядке _parts, как их читал cell_texts, а пишем в порядке архива.
        done: dict[str, bytes] = {}
        for name, kind in _parts(zin):
            blob = done.get(name) or zin.read(name)
            blob, cursor = _rewrite_part(blob, kind, values, cursor)
            done[name] = blob
        for name in zin.namelist():
            if _PERSONS.match(name):
                done[name] = clear_attrs(zin.read(name), _PERSON_ATTRS)
        write_copy(zin, dst, done)


def supported_names(src: str | Path) -> frozenset[str]:
    # слова из ячеек с правовой формой - для строгого режима распознавателя.
    return counterparty_words(cell_texts(src))


# Ячейка листа с координатой: ссылка в общую таблицу (t="s"), текст в листе
# (t="inlineStr") или число - числа пропускаем.
_CELL_RE = re.compile(
    rb'<c\s+r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_V_RE = re.compile(rb"<(?:\w+:)?v>(.*?)</(?:\w+:)?v>", re.S)


def _col_num(letters: bytes) -> int:
    n = 0
    for ch in letters.decode():
        n = n * 26 + (ord(ch) - 64)
    return n


def _sheet_grid(z: zipfile.ZipFile, name: str, shared: list[str]) -> dict[tuple[int, int], str]:
    """Текстовые значения листа по координатам (строка, колонка)."""
    grid: dict[tuple[int, int], str] = {}
    for m in _CELL_RE.finditer(z.read(name)):
        col, row, attrs, body = _col_num(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        if body is None:
            continue
        if b't="s"' in attrs:
            v = _V_RE.search(body)
            if v is not None:
                idx = int(v.group(1))
                if 0 <= idx < len(shared):
                    grid[(row, col)] = shared[idx]
        elif b't="inlineStr"' in attrs:
            grid[(row, col)] = _item_value(body, "is")
    return grid


def labelled_numbers(src: str | Path) -> frozenset[str]:
    # числа, у которых слева или сверху стоит подпись реквизита ("A9=ИНН", "B9=6083778353").
    out: set[str] = set()
    with zipfile.ZipFile(src) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            blob = z.read("xl/sharedStrings.xml")
            shared = [_item_value(i.group(1), "si") for i in _ITEM_RE["si"].finditer(blob)]
        for name in (n for n in z.namelist() if re.match(r"^xl/worksheets/[^/]+\.xml$", n)):
            grid = _sheet_grid(z, name, shared)
            for (row, col), value in grid.items():
                if not DIGITS_ONLY_RE.match(value):
                    continue
                left = grid.get((row, col - 1), "")
                above = grid.get((row - 1, col), "")
                if REQ_LABEL_RE.match(left) or REQ_LABEL_RE.match(above):
                    out.add(value.strip())
    return frozenset(out)


def mask_workbook(src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
    # маскировка xlsx с выводом маппинга
    with zipfile.ZipFile(src) as z:
        unknown = unknown_text_parts(z, {n for n, _ in _parts(z)}, _NO_TEXT)
    if unknown:
        raise ValueError(f"В книге есть текст, с которым возникла проблема обезличивания: {unknown}, может произойти утечка ПД.")

    values = cell_texts(src)
    masker = masker.with_hints(counterparty_words(values), labelled_numbers(src))
    masked, mapping = mask_values(values, masker, mapping)
    rewrite(src, dst, masked)
    return mapping
