'''
Маскировка презентации PowerPoint (.pptx) без внешних зависимостей.
'''
from __future__ import annotations

import posixpath
import re
import zipfile

from ..common.drawingml import chart_units, render, text_units
from ..common.office_xml import clear_attrs
from ..common.package import Package, rels_targets, rels_units

# слайды, заметки, комментарии, макеты и образцы
_TEXT_PARTS = re.compile(
    r"^ppt/(slides/slide\d+|notesSlides/notesSlide\d+|comments/[^/]+"
    r"|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+"
    r"|notesMasters/notesMaster\d+|handoutMasters/handoutMaster\d+"
    r"|diagrams/(?:data|drawing)\d+)\.xml$"      # SmartArt: данные и готовая отрисовка
)
# диаграммы, в том числе нового типа (chartEx)
_CHART_PARTS = re.compile(r"^ppt/charts/chart(?:Ex)?\d+\.xml$")
# порядок обхода: слайды, заметки, комментарии, остальное
_GROUPS = ("ppt/slides/", "ppt/notesSlides/", "ppt/comments/")

# разметка, оформление, связи
_NO_TEXT = re.compile(r"^(\[Content_Types\]\.xml|_rels/|ppt/theme/|customXml/|docProps/)")

# Авторы комментариев: имя, инициалы и учетная запись.
_AUTHORS = re.compile(r"^ppt/(commentAuthors|authors)\.xml$")
_AUTHOR_ATTRS = ("name", "initials", "userId")

# слайд в списке презентации: ссылка на связь с его файлом
_SLIDE_ID_RE = re.compile(rb"""<(?:\w+:)?sldId\s[^>]*?\s\w+:id=(["'])(.*?)\1""")


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
    # части с абзацами в порядке обхода, затем диаграммы, следом связи частей
    names = z.namelist()
    order = {n: i for i, n in enumerate(_slide_order(z))}

    def key(n: str) -> tuple:
        group = next((i for i, g in enumerate(_GROUPS) if n.startswith(g)), len(_GROUPS))
        return group, order.get(n, len(order)), _natural(n)

    text = sorted((n for n in names if _TEXT_PARTS.match(n)), key=key)
    charts = sorted((n for n in names if _CHART_PARTS.match(n)), key=_natural)
    rels = sorted(n for n in names if n.endswith(".rels"))
    return [(n, "text") for n in text] + [(n, "chart") for n in charts] + [(n, "rels") for n in rels]


def _finish(zin: zipfile.ZipFile, done: dict[str, bytes]) -> None:
    # авторы комментариев
    for name in zin.namelist():
        if _AUTHORS.match(name):
            done[name] = clear_attrs(zin.read(name), _AUTHOR_ATTRS)


PPTX = Package("в презентации", _parts, {"text": text_units, "chart": chart_units, "rels": rels_units},
               render, _NO_TEXT, _finish)

paragraph_texts = PPTX.texts
mask_presentation = PPTX.mask
unmask_presentation = PPTX.unmask
