"""Маскировка книги Excel (.xlsx) без внешних зависимостей."""
from __future__ import annotations

import bisect
import re
import zipfile
from pathlib import Path

from .office_xml import (T_RE, cell_label, clear_attrs, counterparty_words, escape, is_label,
                         mask_values, runs_text, tag, unknown_text_parts, unescape,
                         unmask_values, write_copy)

# Контейнеры текстовых узлов <t>: ячейка общей таблицы, ячейка листа, комментарий.
# Автор комментария хранится отдельным узлом, без <t>.
_ITEM_RE = {k: re.compile(tag(k), re.S) for k in ("si", "is", "text", "author")}
# Колонтитул печати листа и текст цепочки примечаний - строкой, без <t>.
_ITEM_RE["hf"] = re.compile(tag("(?:odd|even|first)(?:Header|Footer)"), re.S)
_ITEM_RE["tc"] = _ITEM_RE["text"]
_ITEM_RE["num"] = re.compile(
    rb'<c\s+(?![^>]*\bt="(?:s|inlineStr|b|e)")([^>]*?)(?<!/)>'
    rb'((?:(?!</c>|<c[\s>]).)*?)<(?:\w+:)?v>([^<]*)</(?:\w+:)?v>((?:(?!</c>|<c[\s>]).)*?)</c>',
    re.S)
_PLAIN = {"author", "hf", "tc"}

# Коды колонтитула: &L &C &R (часть), &P &N &D (поля), &"Шрифт,Жирный", &12, &KFF0000.
# Маскируем только текст между ними: "&LСоколова" распознаватель как имя не увидит.
_HF_CODE_RE = re.compile(r'(&(?:"[^"]*"|\d+|K[0-9A-Fa-f]{6}|K\d\d[+-]\d{3}|.))', re.S)

# Части, где мы умеем читать текст, в порядке обхода. Лист не обязан называться sheet1.xml.
_PART_KINDS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^xl/sharedStrings\.xml$"), "si"),
    (re.compile(r"^xl/worksheets/[^/]+\.xml$"), "is"),
    (re.compile(r"^xl/worksheets/[^/]+\.xml$"), "num"),
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


def _num_value(match: re.Match) -> str:
    return unescape(match.group(3).decode("utf-8"))


def _kinds_and_values(path: str | Path) -> list[tuple[str, str]]:
    """Значения книги в порядке cell_texts вместе с видом контейнера."""
    out: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as z:
        for name, kind in _parts(z):
            for item in _ITEM_RE[kind].finditer(z.read(name)):
                if kind == "num":
                    out.append((kind, _num_value(item)))
                else:
                    out.extend((kind, v) for v in _item_values(item.group(1), kind))
    return out


def cell_texts(path: str | Path) -> list[str]:
    """Весь текст книги, который мы умеем обезличивать, в устойчивом порядке."""
    return [value for _, value in _kinds_and_values(path)]


def _rewrite_num_cell(match: re.Match, new: str) -> bytes:
    """Число или результат формулы с найденными ПД - текстовой ячейкой с меткой.
    Формулу убираем: в ее кэше осталось бы исходное значение. Стиль и адрес - как были."""
    attrs = re.sub(rb'\s*\bt="[^"]*"', b"", match.group(1))
    payload = escape(new).encode("utf-8")
    return (b"<c " + attrs.strip() + b' t="inlineStr"><is><t xml:space="preserve">'
            + payload + b"</t></is></c>")


def _rewrite_part(blob: bytes, kind: str, values: list[str], cursor: int) -> tuple[bytes, int]:
    def one_num(match: re.Match) -> bytes:
        nonlocal cursor
        new, cursor = values[cursor], cursor + 1
        if new == _num_value(match):
            return match.group(0)    # ничего не нашлось - число и формула целы
        return _rewrite_num_cell(match, new)

    if kind == "num":
        return _ITEM_RE["num"].sub(one_num, blob), cursor

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
# (t="inlineStr"), число или результат формулы.
_CELL_RE = re.compile(
    rb'<c\s+r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_V_RE = re.compile(rb"<(?:\w+:)?v>(.*?)</(?:\w+:)?v>", re.S)


def _col_num(letters: bytes) -> int:
    n = 0
    for ch in letters.decode():
        n = n * 26 + (ord(ch) - 64)
    return n


def _sheet_grid(z: zipfile.ZipFile, name: str, shared: list[str]) -> dict[tuple[int, int], str]:
    """Значения листа по координатам (строка, колонка): текст и числа."""
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
        elif not re.search(rb'\bt="(?:b|e)"', attrs):
            # число и строка-результат формулы: табельный "124", оклад "95000"
            v = _V_RE.search(body)
            if v is not None:
                grid[(row, col)] = unescape(v.group(1).decode("utf-8"))
    return grid


def _column_headers(grid: dict[tuple[int, int], str]) -> dict[int, list[tuple[int, str]]]:
    """Подписи из реестра по колонкам, сверху вниз: шапка таблицы и шапки ниже по листу."""
    heads: dict[int, list[tuple[int, str]]] = {}
    for (row, col), text in sorted(grid.items()):
        if is_label(text):
            heads.setdefault(col, []).append((row, text))
    return heads


def _header_above(heads: list[tuple[int, str]], row: int) -> str:
    # ближайшая подпись выше по колонке: значения идут сотнями строк под шапкой
    rows = [r for r, _ in heads]
    i = bisect.bisect_left(rows, row)
    return heads[i - 1][1] if i else ""


def labelled_numbers(src: str | Path) -> dict[str, tuple[str, str]]:
    """Значения, их тип и ключ по подписи: слева ("A9=ИНН", "B9=6083778353") или в шапке
    колонки - тогда под ней значения всех строк, а не только первой."""
    out: dict[str, tuple[str, str]] = {}
    with zipfile.ZipFile(src) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            blob = z.read("xl/sharedStrings.xml")
            shared = [_item_value(i.group(1), "si") for i in _ITEM_RE["si"].finditer(blob)]
        for name in (n for n in z.namelist() if re.match(r"^xl/worksheets/[^/]+\.xml$", n)):
            grid = _sheet_grid(z, name, shared)
            heads = _column_headers(grid)
            for (row, col), value in grid.items():
                header = _header_above(heads.get(col, []), row)
                for label in (grid.get((row, col - 1), ""), header):
                    hit = cell_label(label, value)
                    if hit:
                        out[value.strip()] = hit
                        break
    return out


def mask_workbook(src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
    # маскировка xlsx с выводом маппинга
    with zipfile.ZipFile(src) as z:
        unknown = unknown_text_parts(z, {n for n, _ in _parts(z)}, _NO_TEXT)
    if unknown:
        raise ValueError(f"В книге есть текст, с которым возникла проблема обезличивания: {unknown}, может произойти утечка ПД.")

    pairs = _kinds_and_values(src)
    values = [value for _, value in pairs]
    masker = masker.with_hints(counterparty_words(values), labelled_numbers(src))
    masked, mapping = mask_values(values, masker, mapping)
    # Числовая ячейка с ПД становится текстовой
    for (kind, old), new in zip(pairs, masked):
        if kind == "num" and new != old and new in mapping["labels"]:
            mapping["labels"][new]["number"] = True
    rewrite(src, dst, masked)
    return mapping


_MASKED_NUM_RE = re.compile(
    rb'<c ([^>]*?) t="inlineStr"><is><t xml:space="preserve">([^<]*)</t></is></c>')
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_SHEET_RE = re.compile(r"^xl/worksheets/[^/]+\.xml$")


def _restore_numbers(blob: bytes, labels: dict) -> bytes:
    def one(m: re.Match) -> bytes:
        rec = labels.get(unescape(m.group(2).decode("utf-8")))
        if not rec or not rec.get("number") or not _NUMBER_RE.fullmatch(rec["original"]):
            return m.group(0)
        return b"<c " + m.group(1) + b"><v>" + rec["original"].encode("utf-8") + b"</v></c>"

    return _MASKED_NUM_RE.sub(one, blob)


def unmask_workbook(src: str | Path, dst: str | Path, mapping: dict) -> None:
    """Вернуть оригиналы в книгу; ячейка, бывшая числом до маскировки, снова число."""
    src, dst = Path(src), Path(dst)
    if dst.exists() and src.samefile(dst):
        raise ValueError("нельзя писать поверх исходной книги - укажи другой файл")
    labels = mapping.get("labels", {})
    tmp = dst.with_name(dst.name + ".tmp")
    with zipfile.ZipFile(src) as zin:
        done = {name: _restore_numbers(zin.read(name), labels)
                for name in zin.namelist() if _SHEET_RE.match(name)}
        write_copy(zin, tmp, done)
    try:
        rewrite(tmp, dst, unmask_values(cell_texts(tmp), mapping))
    finally:
        tmp.unlink(missing_ok=True)
