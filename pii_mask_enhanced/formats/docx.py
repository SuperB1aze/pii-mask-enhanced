'''
Маскировка документа Word (.docx) без внешних зависимостей.
'''
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, NamedTuple

from .office_xml import *

_TOKEN_RE = re.compile(
    # узел с текстом: видимый текст, удаленный при рецензировании, код поля
    rb"<(?P<name>(?:\w+:)?(?P<kind>t|delText|instrText))(?:\s[^>]*)?"
    rb"(?:/>|(?<!/)>(?P<text>.*?)</(?P=name)>)"
    # короткая запись поля: код в атрибуте, <w:fldSimple w:instr=" HYPERLINK ...">
    rb"|<(?:\w+:)?fldSimple\s[^>]*?(?:\w+:)?instr=(?P<q>[\"'])(?P<instr>.*?)(?P=q)"
    rb"|(?P<p_open><(?:\w+:)?p(?:\s[^>]*)?(?<!/)>)"
    rb"|(?P<p_close></(?:\w+:)?p>)"
    rb"|(?P<fld><(?:\w+:)?fldChar[\s/>])"      # граница поля: коды разных полей не склеиваем
    rb"|(?P<del_close></(?:\w+:)?del>)",       # граница удаленного куска
    re.S)

# Связь части с внешним адресом: ссылка, в том числе mailto:
_REL_RE = re.compile(rb"<(?:\w+:)?Relationship\s[^>]*>")
_EXTERNAL_RE = re.compile(rb"""\sTargetMode=["']External["']""")
_TARGET_RE = re.compile(rb"""\sTarget=(["'])(.*?)\1""", re.S)

# Кто правил и комментировал: в правках, примечаниях и word/people.xml.
_AUTHOR_ATTRS = ("author", "initials", "userId")

# тело, колонтитулы, сноски, примечания
_TEXT_PARTS = re.compile(
    r"^word/(document\.xml|header\d*\.xml|footer\d*\.xml"
    r"|footnotes\.xml|endnotes\.xml|comments\.xml)$"
)

# разметка, стили, связи, нумерация
_NO_TEXT = re.compile(
    r"^(\[Content_Types\]\.xml|_rels/|word/_rels/|word/styles\.xml|word/theme/"
    r"|word/settings\.xml|word/fontTable\.xml|word/webSettings\.xml"
    r"|word/numbering\.xml|word/stylesWithEffects\.xml|customXml/|docProps/)"
)


class _Node(NamedTuple):
    """Кусок текста в части: узел целиком или значение атрибута (name=None)."""
    start: int
    end: int
    raw: bytes
    name: bytes | None


def _element(m: re.Match) -> _Node:
    return _Node(m.start(), m.end(), m.group("text") or b"", m.group("name"))


def _attr(m: re.Match, group: str) -> _Node:
    return _Node(m.start(group), m.end(group), m.group(group), None)


def _text_units(blob: bytes) -> list[list[_Node]]:
    """Единицы маскировки части с абзацами: узлы, текст которых читается одной строкой.
    """
    paragraphs: list[list[list[_Node]]] = []
    stack: list[tuple[list[list[_Node]], dict[bytes, list[_Node]]]] = []
    for m in _TOKEN_RE.finditer(blob):
        if m.group("p_open"):
            units: list[list[_Node]] = [[]]
            paragraphs.append(units)
            stack.append((units, {}))
        elif m.group("p_close"):
            if stack:
                stack.pop()
        elif m.group("fld"):
            if stack:
                stack[-1][1].pop(b"instrText", None)
        elif m.group("del_close"):
            if stack:
                stack[-1][1].pop(b"delText", None)
        elif not stack:
            if (m.group("text") or m.group("instr") or b"").strip():
                raise ValueError("в документе есть текст вне абзаца - "
                                 "обезличить его не выйдет, может произойти утечка ПД")
        elif m.group("q"):
            stack[-1][0].append([_attr(m, "instr")])
        elif m.group("kind") == b"t":
            stack[-1][0][0].append(_element(m))
        else:
            units, open_ = stack[-1]
            if m.group("kind") not in open_:
                open_[m.group("kind")] = []
                units.append(open_[m.group("kind")])
            open_[m.group("kind")].append(_element(m))
    return [unit for units in paragraphs for unit in units]


def _rels_units(blob: bytes) -> list[list[_Node]]:
    # внешние адреса связей; внутренние ведут на части архива, их не трогаем
    units = []
    for rel in _REL_RE.finditer(blob):
        target = _TARGET_RE.search(rel.group(0))
        if target and _EXTERNAL_RE.search(rel.group(0)):
            start = rel.start() + target.start(2)
            units.append([_Node(start, start + len(target.group(2)), target.group(2), None)])
    return units


_UNITS: dict[str, Callable[[bytes], list[list[_Node]]]] = {"text": _text_units, "rels": _rels_units}


# Таблица Word: строки, ячейки (с объединением по ширине - gridSpan), абзацы и их текст.
_TABLE_TOKEN_RE = re.compile(
    rb"<(?P<close>/)?(?:\w+:)?(?P<tag>tbl|tr|tc|p)(?:\s[^>]*)?(?P<self>/)?>"
    rb"|<(?:\w+:)?gridSpan\s[^>]*?(?:\w+:)?val=[\"'](?P<span>\d+)[\"']"
    rb"|<(?:\w+:)?t(?:\s[^>]*)?(?<!/)>(?P<text>.*?)</(?:\w+:)?t>",
    re.S)

# ячейка таблицы: (строка, колонка)
_Grid = dict[tuple[int, int], list[str]]


@dataclass
class _Table:
    """Разбираемая таблица: где мы сейчас и что уже собрано."""
    grid: _Grid = field(default_factory=dict)
    row: int = -1
    col: int = 0
    cell: list[str] | None = None       # абзацы открытой ячейки
    span: int = 1                       # ширина открытой ячейки в колонках
    para: list[bytes] | None = None     # куски текста открытого абзаца

    def open_row(self) -> None:
        self.row, self.col = self.row + 1, 0

    def open_cell(self) -> None:
        self.cell, self.span = [], 1

    def close_cell(self) -> None:
        if self.cell is not None:
            self.grid[(self.row, self.col)] = self.cell
            self.col += self.span
            self.cell = None

    def set_span(self, span: int) -> None:
        if self.cell is not None:
            self.span = span

    def open_para(self) -> None:
        if self.cell is not None:
            self.para = []

    def close_para(self) -> None:
        if self.cell is not None and self.para is not None:
            self.cell.append(unescape(b"".join(self.para).decode("utf-8")))
        self.para = None

    def empty_para(self) -> None:
        # "<w:p/>": абзац без текста - тоже место в ячейке
        if self.cell is not None:
            self.cell.append("")

    def add_text(self, raw: bytes) -> None:
        if self.para is not None:
            self.para.append(raw)


# тег и закрывающий ли он -> что сделать с таблицей; закрытие строки ничего не меняет
_TABLE_EVENTS: dict[tuple[bytes, bool], Callable[[_Table], None]] = {
    (b"tr", False): _Table.open_row,
    (b"tc", False): _Table.open_cell,
    (b"tc", True): _Table.close_cell,
    (b"p", False): _Table.open_para,
    (b"p", True): _Table.close_para,
}


def _tables(blob: bytes) -> list[_Grid]:
    """Таблицы части, вложенные - отдельно: координаты ячеек и тексты абзацев."""
    done: list[_Grid] = []
    stack: list[_Table] = []
    for m in _TABLE_TOKEN_RE.finditer(blob):
        tag, closing, empty = m.group("tag"), bool(m.group("close")), bool(m.group("self"))
        if tag == b"tbl":
            if closing:
                done.append(stack.pop().grid)
            elif not empty:
                stack.append(_Table())
            continue
        if not stack:
            continue        # абзац и текст вне таблицы
        table = stack[-1]
        if m.group("span"):
            table.set_span(int(m.group("span")))
        elif m.group("text") is not None:
            table.add_text(m.group("text"))
        elif tag == b"p" and empty:
            table.empty_para()
        elif (tag, closing) in _TABLE_EVENTS:
            _TABLE_EVENTS[(tag, closing)](table)
    return done


def _header_above(grid: _Grid, row: int, col: int) -> str:
    # ближайшая подпись выше по колонке
    for r in range(row - 1, -1, -1):
        text = " ".join(grid.get((r, col), [])).strip()
        if text and is_label(text):
            return text
    return ""


def table_labels(path: str | Path) -> dict[str, tuple[str, str]]:
    """Значения ячеек таблиц Word по подписи"""
    out: dict[str, tuple[str, str]] = {}
    with zipfile.ZipFile(path) as z:
        for name, kind in _parts(z):
            if kind != "text":
                continue
            for grid in _tables(z.read(name)):
                for (row, col), paras in grid.items():
                    left = next((" ".join(grid[(row, c)]) for c in range(col - 1, -1, -1)
                                 if (row, c) in grid), "")
                    header = _header_above(grid, row, col)
                    for value in paras:
                        if not value.strip():
                            continue
                        for label in (left, header):
                            hit = cell_label(label, value)
                            if hit:
                                out[value.strip()] = hit
                                break
    return out


def _parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    # части с абзацами: тело первым, дальше по алфавиту; следом связи частей
    names = z.namelist()
    text = sorted((n for n in names if _TEXT_PARTS.match(n)),
                  key=lambda n: (n != "word/document.xml", n))
    rels = sorted(n for n in names if n.endswith(".rels"))
    return [(n, "text") for n in text] + [(n, "rels") for n in rels]


def _unit_value(nodes: list[_Node]) -> str:
    return unescape(b"".join(n.raw for n in nodes).decode("utf-8"))


def paragraph_texts(path: str | Path) -> list[str]:
    # текст документа по абзацам, в устойчивом порядке
    with zipfile.ZipFile(path) as z:
        return [_unit_value(nodes) for name, kind in _parts(z)
                for nodes in _UNITS[kind](z.read(name))]


def _render(node: _Node, text: str) -> bytes:
    if node.name is None:
        return escape(text, attr=True).encode("utf-8")
    payload = escape(text).encode("utf-8")
    return b"<" + node.name + b' xml:space="preserve">' + payload + b"</" + node.name + b">"


def _rewrite_part(blob: bytes, kind: str, values: list[str], cursor: int) -> tuple[bytes, int]:
    edits: list[tuple[int, int, bytes]] = []
    for nodes in _UNITS[kind](blob):
        new, cursor = values[cursor], cursor + 1
        if not nodes or _unit_value(nodes) == new:
            continue        # абзац не изменился - оформление цело
        for i, n in enumerate(nodes):
            # весь текст пишем в первый узел, остальные опустошаем
            edits.append((n.start, n.end, _render(n, new if i == 0 else "")))

    out, pos = [], 0
    for start, end, new_node in sorted(edits):
        out += [blob[pos:start], new_node]
        pos = end
    out.append(blob[pos:])
    return b"".join(out), cursor


def rewrite(src: str | Path, dst: str | Path, values: list[str]) -> None:
    # собрать копию документа с подставленными абзацами
    src, dst = Path(src), Path(dst)
    if dst.exists() and src.samefile(dst):
        raise ValueError("нельзя писать поверх исходного документа - укажите другой файл")
    have = paragraph_texts(src)
    if len(values) != len(have):
        raise ValueError(
            f"значений {len(values)}, а абзацев в документе {len(have)} - "
            "подстановка сдвинулась бы по всему тексту")

    cursor = 0
    with zipfile.ZipFile(src) as zin:
        done: dict[str, bytes] = {}
        for name, kind in _parts(zin):
            done[name], cursor = _rewrite_part(zin.read(name), kind, values, cursor)
        for name in zin.namelist():
            if name.endswith(".xml"):
                blob = done.get(name) or zin.read(name)
                cleared = clear_attrs(blob, _AUTHOR_ATTRS)
                if cleared != blob:
                    done[name] = cleared
        write_copy(zin, dst, done)


def mask_document(src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
    # маскировка документа с выводом маппинга
    with zipfile.ZipFile(src) as z:
        unknown = unknown_text_parts(z, {n for n, _ in _parts(z)}, _NO_TEXT)
    if unknown:
        raise ValueError(f"В документе есть текст, с которым возникла проблема обезличивания: {unknown}, может произойти утечка ПД.")

    values = paragraph_texts(src)
    # подпись в предыдущем абзаце и в таблице: слева или в шапке колонки
    labelled = {**numbers_after_labels(values), **table_labels(src)}
    masker = masker.with_hints(counterparty_words(values), labelled)
    masked, mapping = mask_values(values, masker, mapping)
    rewrite(src, dst, masked)
    return mapping


def unmask_document(src: str | Path, dst: str | Path, mapping: dict) -> None:
    # оригиналы обратно в документ: абзацы, колонтитулы, ссылки
    rewrite(src, dst, unmask_values(paragraph_texts(src), mapping))
