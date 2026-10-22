"""Общий каркас форматов с абзацами (.docx, .pptx): единицы текста, таблицы, сборка копии."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, NamedTuple

from .office_xml import (cell_label, counterparty_words, is_label, mask_values, numbers_after_labels,
                         unescape, unknown_text_parts, unmask_values, write_copy)


class Node(NamedTuple):
    """Кусок текста в части: узел целиком или значение атрибута (name=None)."""
    start: int
    end: int
    raw: bytes
    name: bytes | None


# единицы маскировки части: узлы, текст которых читается одной строкой
Units = Callable[[bytes], list[list[Node]]]


def unit_value(nodes: list[Node]) -> str:
    return unescape(b"".join(n.raw for n in nodes).decode("utf-8"))


# Связь части с внешним адресом: ссылка, в том числе mailto:
_REL_RE = re.compile(rb"<(?:\w+:)?Relationship\s[^>]*>")
_EXTERNAL_RE = re.compile(rb"""\sTargetMode=["']External["']""")
_TARGET_RE = re.compile(rb"""\sTarget=(["'])(.*?)\1""", re.S)
_ID_RE = re.compile(rb"""\sId=(["'])(.*?)\1""")


def rels_units(blob: bytes) -> list[list[Node]]:
    # внешние адреса связей; внутренние ведут на части архива, их не трогаем
    units = []
    for rel in _REL_RE.finditer(blob):
        target = _TARGET_RE.search(rel.group(0))
        if target and _EXTERNAL_RE.search(rel.group(0)):
            start = rel.start() + target.start(2)
            units.append([Node(start, start + len(target.group(2)), target.group(2), None)])
    return units


def rels_targets(blob: bytes) -> dict[bytes, bytes]:
    """Связи части: Id -> Target."""
    out = {}
    for rel in _REL_RE.finditer(blob):
        rid, target = _ID_RE.search(rel.group(0)), _TARGET_RE.search(rel.group(0))
        if rid and target:
            out[rid.group(2)] = target.group(2)
    return out


def _rewrite_units(blob: bytes, units: list[list[Node]], values: list[str], cursor: int,
                   render: Callable[[Node, str], bytes]) -> tuple[bytes, int]:
    # подставить значения в единицы части по порядку; cursor - номер первого значения
    edits: list[tuple[int, int, bytes]] = []
    for nodes in units:
        new, cursor = values[cursor], cursor + 1
        if not nodes or unit_value(nodes) == new:
            continue        # абзац не изменился - оформление цело
        for i, n in enumerate(nodes):
            # весь текст пишем в первый узел, остальные опустошаем
            edits.append((n.start, n.end, render(n, new if i == 0 else "")))

    out, pos = [], 0
    for start, end, new_node in sorted(edits):
        out += [blob[pos:start], new_node]
        pos = end
    out.append(blob[pos:])
    return b"".join(out), cursor


# Таблица Word и слайда: строки, ячейки (с объединением по ширине - gridSpan), абзацы и их текст.
# На слайде объединенные ячейки стоят в строке пустыми (<a:tc hMerge="1">), колонки не съезжают.
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


def _part_table_labels(blob: bytes) -> dict[str, tuple[str, str]]:
    # значения ячеек по подписи: слева в строке или в шапке колонки
    out: dict[str, tuple[str, str]] = {}
    for grid in _tables(blob):
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


@dataclass(frozen=True)
class Package:
    """Формат с абзацами: что в нем читать и как писать обратно."""
    where: str                                                   # "в документе" - для сообщений
    parts: Callable[[zipfile.ZipFile], list[tuple[str, str]]]    # части в порядке обхода и их вид
    units: dict[str, Units]                                      # вид части -> разбор на единицы
    render: Callable[[Node, str], bytes]                         # узел с новым текстом
    no_text: re.Pattern                                          # части, где текста не бывает
    finish: Callable[[zipfile.ZipFile, dict[str, bytes]], None]  # вычистить авторов и прочее

    def texts(self, path: str | Path) -> list[str]:
        # текст по единицам, в устойчивом порядке
        with zipfile.ZipFile(path) as z:
            return [unit_value(nodes) for name, kind in self.parts(z)
                    for nodes in self.units[kind](z.read(name))]

    def _labels(self, z: zipfile.ZipFile) -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        for name, kind in self.parts(z):
            if kind == "text":
                out.update(_part_table_labels(z.read(name)))
        return out

    def table_labels(self, path: str | Path) -> dict[str, tuple[str, str]]:
        """Значения ячеек таблиц по подписи."""
        with zipfile.ZipFile(path) as z:
            return self._labels(z)

    def rewrite(self, src: str | Path, dst: str | Path, values: list[str]) -> None:
        # собрать копию файла с подставленными значениями
        src, dst = Path(src), Path(dst)
        if dst.exists() and src.samefile(dst):
            raise ValueError("нельзя писать поверх исходного файла - укажите другой файл")
        have = self.texts(src)
        if len(values) != len(have):
            raise ValueError(
                f"значений {len(values)}, а строк текста {self.where} {len(have)} - "
                "подстановка сдвинулась бы по всему тексту")

        cursor = 0
        with zipfile.ZipFile(src) as zin:
            done: dict[str, bytes] = {}
            for name, kind in self.parts(zin):
                blob = zin.read(name)
                done[name], cursor = _rewrite_units(blob, self.units[kind](blob), values,
                                                    cursor, self.render)
            self.finish(zin, done)
            write_copy(zin, dst, done)

    def mask(self, src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
        # маскировка с выводом маппинга
        with zipfile.ZipFile(src) as z:
            unknown = unknown_text_parts(z, {n for n, _ in self.parts(z)}, self.no_text)
            if unknown:
                raise ValueError(f"{self.where.capitalize()} есть текст, с которым возникла проблема "
                                 f"обезличивания: {unknown}, может произойти утечка ПД.")
            tables = self._labels(z)

        values = self.texts(src)
        # подпись в предыдущей строке и в таблице: слева или в шапке колонки
        labelled = {**numbers_after_labels(values), **tables}
        masker = masker.with_hints(counterparty_words(values), labelled)
        masked, mapping = mask_values(values, masker, mapping)
        self.rewrite(src, dst, masked)
        return mapping

    def unmask(self, src: str | Path, dst: str | Path, mapping: dict) -> None:
        # оригиналы обратно в файл того же формата
        self.rewrite(src, dst, unmask_values(self.texts(src), mapping))
