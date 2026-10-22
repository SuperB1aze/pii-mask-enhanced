'''
Маскировка документа Word (.docx) без внешних зависимостей.
'''
from __future__ import annotations

import re
import zipfile

from ..common.office_xml import clear_attrs, escape
from ..common.package import Node, Package, rels_units

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


def _element(m: re.Match) -> Node:
    return Node(m.start(), m.end(), m.group("text") or b"", m.group("name"))


def _attr(m: re.Match, group: str) -> Node:
    return Node(m.start(group), m.end(group), m.group(group), None)


def _text_units(blob: bytes) -> list[list[Node]]:
    """Единицы маскировки части с абзацами: узлы, текст которых читается одной строкой.
    """
    paragraphs: list[list[list[Node]]] = []
    stack: list[tuple[list[list[Node]], dict[bytes, list[Node]]]] = []
    for m in _TOKEN_RE.finditer(blob):
        if m.group("p_open"):
            units: list[list[Node]] = [[]]
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


def _parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    # части с абзацами: тело первым, дальше по алфавиту; следом связи частей
    names = z.namelist()
    text = sorted((n for n in names if _TEXT_PARTS.match(n)),
                  key=lambda n: (n != "word/document.xml", n))
    rels = sorted(n for n in names if n.endswith(".rels"))
    return [(n, "text") for n in text] + [(n, "rels") for n in rels]


def _render(node: Node, text: str) -> bytes:
    if node.name is None:
        return escape(text, attr=True).encode("utf-8")
    payload = escape(text).encode("utf-8")
    return b"<" + node.name + b' xml:space="preserve">' + payload + b"</" + node.name + b">"


def _finish(zin: zipfile.ZipFile, done: dict[str, bytes]) -> None:
    # авторы правок и примечаний бывают в любой части
    for name in zin.namelist():
        if name.endswith(".xml"):
            blob = done.get(name) or zin.read(name)
            cleared = clear_attrs(blob, _AUTHOR_ATTRS)
            if cleared != blob:
                done[name] = cleared


DOCX = Package("в документе", _parts, {"text": _text_units, "rels": rels_units},
               _render, _NO_TEXT, _finish)

paragraph_texts = DOCX.texts
table_labels = DOCX.table_labels
rewrite = DOCX.rewrite
mask_document = DOCX.mask
unmask_document = DOCX.unmask
