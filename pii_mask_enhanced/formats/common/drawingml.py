"""Текст DrawingML: слайды, фигуры и надписи, SmartArt, диаграммы - во всех форматах Office."""
from __future__ import annotations

import re

from .office_xml import escape
from .package import Node

_TOKEN_RE = re.compile(
    # текст прогона и поля (номер слайда, дата). Только текст без тегов: <dgm:t> в SmartArt -
    # контейнер с абзацами, а не текстовый узел
    rb"<(?P<name>(?:\w+:)?t)(?:\s[^>]*)?(?:/>|(?<!/)>(?P<text>[^<]*)</(?P=name)>)"
    # комментарий PowerPoint старого образца: текст одной строкой, без абзацев
    rb"|<(?P<cname>(?:\w+:)?text)(?:\s[^>]*)?(?:/>|(?<!/)>(?P<ctext>[^<]*)</(?P=cname)>)"
    # свойства фигуры: в них замещающий текст картинки
    rb"|<(?:\w+:)?cNvPr\s(?P<cnv>[^>]*)>"
    rb"|(?P<p_open><(?:\w+:)?p(?:\s[^>]*)?(?<!/)>)"
    rb"|(?P<p_close></(?:\w+:)?p>)"
    rb"|(?P<br><(?:\w+:)?br[\s/>])"
    rb"|(?P<fld_open><(?:\w+:)?fld[\s>])"
    rb"|(?P<fld_close></(?:\w+:)?fld>)",
    re.S)

# замещающий текст и заголовок фигуры
ALT_RE = re.compile(rb"""\s(?:descr|title)=(["'])(.*?)\1""", re.S)

# Значение в кэше диаграммы - копия ячейки: <c:v> (подписи, имена рядов, числа)
# и <cx:pt> у диаграмм нового типа. <c:pt> держит значение во вложенном <c:v>.
_CACHE_RE = re.compile(rb"<(?P<name>(?:\w+:)?(?:v|pt))(?:\s[^>]*)?(?<!/)>(?P<text>[^<]+)</(?P=name)>")


def alt_units(attrs: bytes, base: int) -> list[list[Node]]:
    """Замещающий текст из атрибутов тега; base - смещение атрибутов в части."""
    return [[Node(base + a.start(2), base + a.end(2), a.group(2), None)] for a in ALT_RE.finditer(attrs)]


def text_units(blob: bytes) -> list[list[Node]]:
    """Единицы маскировки: строка абзаца (до разрыва <a:br/>), комментарий, замещающий текст."""
    units: list[list[Node]] = []
    line: list[Node] | None = None
    in_field = False
    for m in _TOKEN_RE.finditer(blob):
        if m.group("p_open"):
            line = []
            units.append(line)
        elif m.group("p_close"):
            line = None
        elif m.group("br"):
            if line is not None:
                line = []
                units.append(line)
        elif m.group("fld_open"):
            in_field = True
        elif m.group("fld_close"):
            in_field = False
        elif m.group("cnv") is not None:
            units += alt_units(m.group("cnv"), m.start("cnv"))
        elif m.group("cname"):
            units.append([Node(m.start(), m.end(), m.group("ctext") or b"", m.group("cname"))])
        elif in_field:
            continue        # текст поля приложение пересчитывает само: туда не пишем
        elif line is None:
            if (m.group("text") or b"").strip():
                raise ValueError("в файле есть текст вне абзаца - "
                                 "обезличить его не выйдет, может произойти утечка ПД")
        else:
            line.append(Node(m.start(), m.end(), m.group("text") or b"", m.group("name")))
    return units


def chart_units(blob: bytes) -> list[list[Node]]:
    """Диаграмма: заголовки и подписи абзацами, затем значения кэша по одному."""
    return text_units(blob) + [[Node(m.start("text"), m.end("text"), m.group("text"), None)]
                               for m in _CACHE_RE.finditer(blob)]


def render(node: Node, text: str) -> bytes:
    if node.name is None:
        return escape(text, attr=True).encode("utf-8")
    # по схеме DrawingML у <a:t> атрибутов нет - xml:space, как в Word, не пишем
    return b"<" + node.name + b">" + escape(text).encode("utf-8") + b"</" + node.name + b">"
