"""Маскировка книги Excel (.xlsx) без внешних зависимостей."""
from __future__ import annotations

import bisect
import re
import zipfile
from pathlib import Path

from ..common import drawingml
from ..common.base import OfficeFormat
from ..common.office_xml import (T_RE, cell_label, clear_attrs, escape, is_label, mask_values,
                                 runs_text, tag, unescape, unmask_values, write_copy)
from ..common.package import Node, rewrite_units, unit_value

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
    # фигуры и надписи, SmartArt, диаграммы, кэш сводных таблиц - разбор на единицы
    (re.compile(r"^xl/(?:drawings/drawing\d+|diagrams/(?:data|drawing)\d+)\.xml$"), "drawing"),
    (re.compile(r"^xl/charts/chart(?:Ex)?\d+\.xml$"), "chart"),
    (re.compile(r"^xl/pivotCache/pivotCache(?:Definition|Records)\d+\.xml$"), "pivot"),
)

# Кэш сводной таблицы - копия исходных строк: текстовое значение в атрибуте <s v="...">.
_PIVOT_STRING_RE = re.compile(rb"""<(?:\w+:)?s\s[^>]*?\bv=(["'])(.*?)\1""", re.S)


def _pivot_units(blob: bytes) -> list[list[Node]]:
    return [[Node(m.start(2), m.end(2), m.group(2), None)] for m in _PIVOT_STRING_RE.finditer(blob)]


_UNITS = {"drawing": drawingml.text_units, "chart": drawingml.chart_units, "pivot": _pivot_units}

# Следы автора в атрибутах: кто писал примечания, где сохранялась книга (путь с именем
# пользователя), кто защитил ее от записи, кто обновлял сводную таблицу.
_AUTHOR_ATTRS = (
    (re.compile(r"^xl/persons/[^/]+\.xml$"), ("displayName", "userId")),
    (re.compile(r"^xl/workbook\.xml$"), ("url", "userName")),
    (re.compile(r"^xl/pivotCache/pivotCacheDefinition\d+\.xml$"), ("refreshedBy",)),
)

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
    """Значения книги в порядке Workbook.texts вместе с видом контейнера."""
    out: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as z:
        for name, kind in _parts(z):
            if kind in _UNITS:
                out.extend((kind, unit_value(nodes)) for nodes in _UNITS[kind](z.read(name)))
                continue
            for item in _ITEM_RE[kind].finditer(z.read(name)):
                if kind == "num":
                    out.append((kind, _num_value(item)))
                else:
                    out.extend((kind, v) for v in _item_values(item.group(1), kind))
    return out


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
    if kind in _UNITS:
        return rewrite_units(blob, _UNITS[kind](blob), values, cursor, drawingml.render)

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


# Имя листа: атрибут в workbook.xml и ссылки на лист - в формулах, именованных диапазонах,
# диаграммах (<c:f>) и источнике сводной таблицы.
_WORKBOOK = "xl/workbook.xml"
_SHEET_TAG_RE = re.compile(rb"""(<(?:\w+:)?sheet\s[^>]*?\bname=)(["'])(.*?)\2""", re.S)
_FORMULA_RE = re.compile(
    rb"(<(?P<tag>(?:\w+:)?(?:f|definedName))(?:\s[^>]*)?(?<!/)>)(.*?)(</(?P=tag)>)", re.S)
_SOURCE_SHEET_RE = re.compile(rb"""(<(?:\w+:)?worksheetSource\s[^>]*?\bsheet=)(["'])(.*?)\2""", re.S)
_SHEET_NAME_MAX = 31


def _sheet_ref_re(old: str) -> re.Pattern:
    # 'Имя листа'!A1 (кавычка внутри имени удваивается) и, если имя простое, Имя!A1
    alts = [re.escape("'" + old.replace("'", "''") + "'!")]
    if re.fullmatch(r"[^\W\d][\w.]*", old):
        alts.append(r"(?<![\w.'])" + re.escape(old) + "!")
    return re.compile("|".join(alts))


def _rename_sheets(blob: bytes, renames: dict[str, str]) -> bytes:
    """Подставить новые имена листов в атрибуты и ссылки части."""
    refs = [(_sheet_ref_re(old), "'" + new.replace("'", "''") + "'!") for old, new in renames.items()]

    def formula(m: re.Match) -> bytes:
        old = unescape(m.group(3).decode("utf-8"))
        new = old
        for rx, ref in refs:
            new = rx.sub(lambda _: ref, new)
        return m.group(0) if new == old else m.group(1) + escape(new).encode("utf-8") + m.group(4)

    def attr(m: re.Match) -> bytes:
        name = renames.get(unescape(m.group(3).decode("utf-8")))
        if name is None:
            return m.group(0)
        return m.group(1) + m.group(2) + escape(name, attr=True).encode("utf-8") + m.group(2)

    blob = _FORMULA_RE.sub(formula, blob)
    blob = _SOURCE_SHEET_RE.sub(attr, blob)
    return _SHEET_TAG_RE.sub(attr, blob)


def _new_sheet_names(names: list[str], renamed: list[str]) -> dict[str, str]:
    """Старое имя -> новое; имя после замены обязано остаться допустимым и уникальным."""
    out: dict[str, str] = {}
    used = set(names)
    for i, (old, new) in enumerate(zip(names, renamed), 1):
        if new == old:
            continue
        if len(new) > _SHEET_NAME_MAX:
            new = f"Лист{i}"            # длинное имя Excel не примет: лучше безличное, чем исходное
        base, n = new, 2
        while new in used:
            new = f"{base[:_SHEET_NAME_MAX - 4]} ({n})"
            n += 1
        used.add(new)
        out[old] = new
    return out


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


_MASKED_NUM_RE = re.compile(
    rb'<c ([^>]*?) t="inlineStr"><is><t xml:space="preserve">([^<]*)</t></is></c>')
# Excel при пересохранении переносит метку в общую таблицу строк, в ячейке остается номер строки
_SHARED_NUM_RE = re.compile(rb'<c ([^>]*?)\bt="s"([^>]*)><v>(\d+)</v></c>')
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_SHEET_RE = re.compile(r"^xl/worksheets/[^/]+\.xml$")
_SHARED_STRINGS = "xl/sharedStrings.xml"


def _restore_numbers(blob: bytes, labels: dict, shared: list[str]) -> bytes:
    def number(label: str) -> bytes | None:
        rec = labels.get(label)
        if not rec or not rec.get("number") or not _NUMBER_RE.fullmatch(rec["original"]):
            return None
        return rec["original"].encode("utf-8")

    def inline(m: re.Match) -> bytes:
        value = number(unescape(m.group(2).decode("utf-8")))
        return m.group(0) if value is None else b"<c " + m.group(1) + b"><v>" + value + b"</v></c>"

    def from_shared(m: re.Match) -> bytes:
        i = int(m.group(3))
        value = number(shared[i]) if i < len(shared) else None
        if value is None:
            return m.group(0)
        attrs = b" ".join(a for a in (m.group(1).strip(), m.group(2).strip()) if a)
        return b"<c " + attrs + b"><v>" + value + b"</v></c>"

    return _SHARED_NUM_RE.sub(from_shared, _MASKED_NUM_RE.sub(inline, blob))


class Workbook(OfficeFormat):
    """Книга Excel: ячейки, примечания, колонтитулы, фигуры, диаграммы, сводные таблицы, имена листов."""
    where = "в книге"
    what = "книг"
    no_text = _NO_TEXT
    parts = staticmethod(_parts)

    def texts(self, path: str | Path) -> list[str]:
        return [value for _, value in _kinds_and_values(path)]

    def sheet_names(self, path: str | Path) -> list[str]:
        """Имена листов книги в порядке workbook.xml."""
        with zipfile.ZipFile(path) as z:
            if _WORKBOOK not in z.namelist():
                return []
            return [unescape(m.group(3).decode("utf-8"))
                    for m in _SHEET_TAG_RE.finditer(z.read(_WORKBOOK))]

    def labels(self, path: str | Path) -> dict[str, tuple[str, str]]:
        """Значения, их тип и ключ по подписи: слева ("A9=ИНН", "B9=6083778353") или в шапке
        колонки - тогда под ней значения всех строк, а не только первой."""
        out: dict[str, tuple[str, str]] = {}
        with zipfile.ZipFile(path) as z:
            shared = []
            if _SHARED_STRINGS in z.namelist():
                blob = z.read(_SHARED_STRINGS)
                shared = [_item_value(i.group(1), "si") for i in _ITEM_RE["si"].finditer(blob)]
            for name in (n for n in z.namelist() if _SHEET_RE.match(n)):
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

    def rewrite(self, src: str | Path, dst: str | Path, values: list[str],
                renames: dict[str, str] | None = None) -> None:
        """Собрать копию книги с подставленными значениями.

        `values` - результат `texts` для этой же книги, в том же порядке.
        `renames` - новые имена листов: старое -> новое, вместе со ссылками на них.
        """
        src, dst = Path(src), Path(dst)
        self._check_rewrite(src, dst, values)

        cursor = 0
        with zipfile.ZipFile(src) as zin:
            # Правим в порядке _parts, как их читал texts, а пишем в порядке архива.
            done: dict[str, bytes] = {}
            for name, kind in _parts(zin):
                blob = done.get(name) or zin.read(name)
                blob, cursor = _rewrite_part(blob, kind, values, cursor)
                done[name] = blob
            for name in zin.namelist():
                attrs = [a for rx, names in _AUTHOR_ATTRS if rx.match(name) for a in names]
                rename = bool(renames) and name.startswith("xl/") and name.endswith(".xml")
                if not attrs and not rename:
                    continue
                blob = done.get(name) or zin.read(name)
                new = clear_attrs(blob, tuple(attrs)) if attrs else blob
                if rename:
                    new = _rename_sheets(new, renames)
                if new != blob:
                    done[name] = new
            write_copy(zin, dst, done)

    def mask(self, src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
        # маскировка xlsx с выводом маппинга
        with zipfile.ZipFile(src) as z:
            self._check_known(z)

        pairs = _kinds_and_values(src)
        values = [value for _, value in pairs]
        masked, mapping, masker = self._mask_texts(values, masker, mapping, self.labels(src))
        # Числовая ячейка с ПД становится текстовой
        for (kind, old), new in zip(pairs, masked):
            if kind == "num" and new != old and new in mapping["labels"]:
                mapping["labels"][new]["number"] = True
        # имя листа бывает ФИО ("Соколова А.В.") - маскируется вместе со ссылками на лист
        names = self.sheet_names(src)
        renamed, mapping = mask_values(names, masker, mapping)
        self.rewrite(src, dst, masked, _new_sheet_names(names, renamed))
        return mapping

    def unmask(self, src: str | Path, dst: str | Path, mapping: dict) -> None:
        """Вернуть оригиналы в книгу; ячейка, бывшая числом до маскировки, снова число."""
        src, dst = Path(src), Path(dst)
        self._check_target(src, dst)
        labels = mapping.get("labels", {})
        tmp = dst.with_name(dst.name + ".tmp")
        with zipfile.ZipFile(src) as zin:
            shared = ([runs_text(m.group(1)) for m in _ITEM_RE["si"].finditer(zin.read(_SHARED_STRINGS))]
                      if _SHARED_STRINGS in zin.namelist() else [])
            done = {name: _restore_numbers(zin.read(name), labels, shared)
                    for name in zin.namelist() if _SHEET_RE.match(name)}
            write_copy(zin, tmp, done)
        names = self.sheet_names(src)
        renames = {old: new for old, new in zip(names, unmask_values(names, mapping)) if new != old}
        try:
            self.rewrite(tmp, dst, unmask_values(self.texts(tmp), mapping), renames)
        finally:
            tmp.unlink(missing_ok=True)


XLSX = Workbook()
