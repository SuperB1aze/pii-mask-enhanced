'''
Маскировка презентации PowerPoint (.pptx) без внешних зависимостей.
'''
from __future__ import annotations

import posixpath
import re
import zipfile

from ..common.office_xml import clear_attrs, escape
from ..common.package import Node, Package, rels_targets, rels_units

_TOKEN_RE = re.compile(
    # текст прогона и поля (номер слайда, дата)
    rb"<(?P<name>(?:\w+:)?t)(?:\s[^>]*)?(?:/>|(?<!/)>(?P<text>.*?)</(?P=name)>)"
    # комментарий старого образца: текст одной строкой, без абзацев
    rb"|<(?P<cname>(?:\w+:)?text)(?:\s[^>]*)?(?:/>|(?<!/)>(?P<ctext>.*?)</(?P=cname)>)"
    # свойства фигуры: в них замещающий текст картинки
    rb"|<(?:\w+:)?cNvPr\s(?P<cnv>[^>]*)>"
    rb"|(?P<p_open><(?:\w+:)?p(?:\s[^>]*)?(?<!/)>)"
    rb"|(?P<p_close></(?:\w+:)?p>)"
    rb"|(?P<br><(?:\w+:)?br[\s/>])"
    rb"|(?P<fld_open><(?:\w+:)?fld[\s>])"
    rb"|(?P<fld_close></(?:\w+:)?fld>)",
    re.S)

# замещающий текст и заголовок фигуры
_ALT_RE = re.compile(rb"""\s(?:descr|title)=(["'])(.*?)\1""", re.S)

# слайды, заметки, комментарии, макеты и образцы
_TEXT_PARTS = re.compile(
    r"^ppt/(slides/slide\d+|notesSlides/notesSlide\d+|comments/[^/]+"
    r"|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+"
    r"|notesMasters/notesMaster\d+|handoutMasters/handoutMaster\d+)\.xml$"
)
# порядок обхода: слайды, заметки, комментарии, остальное
_GROUPS = ("ppt/slides/", "ppt/notesSlides/", "ppt/comments/")

# разметка, оформление, связи
_NO_TEXT = re.compile(r"^(\[Content_Types\]\.xml|_rels/|ppt/theme/|customXml/|docProps/)")

# Авторы комментариев: имя, инициалы и учетная запись.
_AUTHORS = re.compile(r"^ppt/(commentAuthors|authors)\.xml$")
_AUTHOR_ATTRS = ("name", "initials", "userId")

# Заголовки слайдов в свойствах файла - копия текста слайдов.
_TITLES_RE = re.compile(rb"<(?:\w+:)?TitlesOfParts>.*?</(?:\w+:)?TitlesOfParts>", re.S)
_LPSTR_RE = re.compile(rb"(<(?:\w+:)?lpstr>)[^<]*(</(?:\w+:)?lpstr>)")

# слайд в списке презентации: ссылка на связь с его файлом
_SLIDE_ID_RE = re.compile(rb"""<(?:\w+:)?sldId\s[^>]*?\s\w+:id=(["'])(.*?)\1""")


def _text_units(blob: bytes) -> list[list[Node]]:
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
            base = m.start("cnv")
            for a in _ALT_RE.finditer(m.group("cnv")):
                units.append([Node(base + a.start(2), base + a.end(2), a.group(2), None)])
        elif m.group("cname"):
            units.append([Node(m.start(), m.end(), m.group("ctext") or b"", m.group("cname"))])
        elif in_field:
            continue        # текст поля PowerPoint пересчитывает сам: туда не пишем
        elif line is None:
            if (m.group("text") or b"").strip():
                raise ValueError("в презентации есть текст вне абзаца - "
                                 "обезличить его не выйдет, может произойти утечка ПД")
        else:
            line.append(Node(m.start(), m.end(), m.group("text") or b"", m.group("name")))
    return units


def _natural(name: str) -> list:
    # slide2 раньше slide10
    return [int(s) if s.isdigit() else s for s in re.split(r"(\d+)", name)]


def _slide_order(z: zipfile.ZipFile) -> list[str]:
    # порядок показа задает presentation.xml, номер в имени файла его не отражает
    try:
        pres = z.read("ppt/presentation.xml")
        rels = z.read("ppt/_rels/presentation.xml.rels")
    except KeyError:
        return []
    targets = {}
    for rid, target in rels_targets(rels).items():
        path = target.decode("utf-8")
        targets[rid] = (path.lstrip("/") if path.startswith("/")
                        else posixpath.normpath(posixpath.join("ppt", path)))
    return [targets[m.group(2)] for m in _SLIDE_ID_RE.finditer(pres) if m.group(2) in targets]


def _parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    # части с абзацами в порядке обхода; следом связи частей
    names = z.namelist()
    order = {n: i for i, n in enumerate(_slide_order(z))}

    def key(n: str) -> tuple:
        group = next((i for i, g in enumerate(_GROUPS) if n.startswith(g)), len(_GROUPS))
        return group, order.get(n, len(order)), _natural(n)

    text = sorted((n for n in names if _TEXT_PARTS.match(n)), key=key)
    rels = sorted(n for n in names if n.endswith(".rels"))
    return [(n, "text") for n in text] + [(n, "rels") for n in rels]


def _render(node: Node, text: str) -> bytes:
    if node.name is None:
        return escape(text, attr=True).encode("utf-8")
    # по схеме DrawingML у <a:t> атрибутов нет - xml:space, как в Word, не пишем
    return b"<" + node.name + b">" + escape(text).encode("utf-8") + b"</" + node.name + b">"


def _finish(zin: zipfile.ZipFile, done: dict[str, bytes]) -> None:
    # авторы комментариев и копия заголовков слайдов в свойствах файла
    for name in zin.namelist():
        if _AUTHORS.match(name):
            done[name] = clear_attrs(zin.read(name), _AUTHOR_ATTRS)
        elif name == "docProps/app.xml":
            done[name] = _TITLES_RE.sub(lambda m: _LPSTR_RE.sub(rb"\1\2", m.group(0)), zin.read(name))


PPTX = Package("в презентации", _parts, {"text": _text_units, "rels": rels_units},
               _render, _NO_TEXT, _finish)

paragraph_texts = PPTX.texts
mask_presentation = PPTX.mask
unmask_presentation = PPTX.unmask
