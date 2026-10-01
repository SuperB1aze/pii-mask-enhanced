'''
Маскировка документа Word (.docx) без внешних зависимостей.
'''
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .xlsx import _escape, _strip_authors, _unescape

# Теги абзаца (<w:p>) и текста (<w:t>). 
# Префикс "w:" необязателен: сторонние конвертеры иногда пишут теги без него.
_P_RE = re.compile(rb"<(?:\w+:)?p(?:\s[^>]*)?>(.*?)</(?:\w+:)?p>", re.S)
_T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?>(.*?)</(?:\w+:)?t>|<(?:\w+:)?t(?:\s[^>]*)?/>", re.S)
_ANY_T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?>([^<]+)</(?:\w+:)?t>", re.S)

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


def _parts(z: zipfile.ZipFile) -> list[str]:
    # части с абзацами: тело первым, дальше по алфавиту
    names = [n for n in z.namelist() if _TEXT_PARTS.match(n)]
    return sorted(names, key=lambda n: (n != "word/document.xml", n))


def _unknown_text_parts(z: zipfile.ZipFile) -> list[str]:
    # диаграммы, надписи, чужое
    known = set(_parts(z))
    bad = []
    for n in z.namelist():
        if n in known or _NO_TEXT.match(n) or not n.endswith(".xml"):
            continue
        if any(m.group(1).strip() for m in _ANY_T_RE.finditer(z.read(n))):
            bad.append(n)
    return sorted(bad)


def _para_value(body: bytes) -> str:
    runs = [m.group(1) or b"" for m in _T_RE.finditer(body)]
    return _unescape(b"".join(runs).decode("utf-8"))


def paragraph_texts(path: str | Path) -> list[str]:
    # текст документа по абзацам, в устойчивом порядке
    values: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name in _parts(z):
            for p in _P_RE.finditer(z.read(name)):
                values.append(_para_value(p.group(1)))
    return values


def _rewrite_part(blob: bytes, values: list[str], cursor: int) -> tuple[bytes, int]:
    def one(match: re.Match) -> bytes:
        nonlocal cursor
        body = match.group(1)
        new, cursor = values[cursor], cursor + 1
        if _para_value(body) == new:
            return match.group(0)      # абзац не изменился - оформление цело

        payload = _escape(new).encode("utf-8")
        first = True

        def run(_t: re.Match) -> bytes:
            nonlocal first
            if not first:
                return b'<w:t xml:space="preserve"></w:t>'
            first = False
            return b'<w:t xml:space="preserve">' + payload + b"</w:t>"

        whole = match.group(0)
        head = whole[:match.start(1) - match.start(0)]
        tail = whole[match.end(1) - match.start(0):]
        return head + _T_RE.sub(run, body) + tail

    return _P_RE.sub(one, blob), cursor


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
        for name in _parts(zin):
            done[name], cursor = _rewrite_part(zin.read(name), values, cursor)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                blob = done.get(info.filename) or zin.read(info.filename)
                if info.filename == "docProps/core.xml":
                    blob = _strip_authors(blob)
                zout.writestr(info, blob)


def mask_document(src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
    # маскировка документа с выводом маппинга
    with zipfile.ZipFile(src) as z:
        unknown = _unknown_text_parts(z)
    if unknown:
        raise ValueError(f"В документе есть текст, с которым возникла проблема обезличивания: {unknown}, может произойти утечка ПД.")

    masked = []
    for value in paragraph_texts(src):
        if not value.strip():
            masked.append(value)
            continue
        out, mapping = masker.mask(value, mapping)
        masked.append(out)
    rewrite(src, dst, masked)
    return mapping
