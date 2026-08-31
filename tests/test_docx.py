"""Маскировка документа Word: текст меняется, оформление остается.

Word рвет фразу на куски по форматированию и следам правки: "Иванов" в файле
запросто лежит двумя узлами - "Иван" и "ов". Поэтому единица работы - абзац
целиком, а не отдельный узел: иначе распознаватель не увидит ни одного имени.
"""
import zipfile

import pytest

from pii_mask import docx

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _para(runs: list[str], bold_first: bool = False) -> str:
    """Абзац из нескольких прогонов - так Word и хранит текст."""
    out = []
    for i, r in enumerate(runs):
        props = "<w:rPr><w:b/></w:rPr>" if (bold_first and i == 0) else ""
        out.append(f"<w:r>{props}<w:t>{r}</w:t></w:r>")
    return f"<w:p>{''.join(out)}</w:p>"


def _docx(path, paragraphs: list[str], extra: dict[str, str] | None = None):
    body = "".join(paragraphs)
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}>'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", doc)
        for name, blob in (extra or {}).items():
            z.writestr(name, blob)
    return path


def test_reads_paragraph_as_whole(tmp_path):
    """Абзац из кусков читается одной строкой - иначе имя не найти."""
    src = _docx(tmp_path / "a.docx", [_para(["Соко", "лова Анна ", "Владимировна"])])
    assert docx.paragraph_texts(src) == ["Соколова Анна Владимировна"]


def test_masks_name_split_across_runs(tmp_path):
    """Главный случай: имя разорвано форматированием."""
    from pii_mask.core import Masker

    src = _docx(tmp_path / "b.docx", [_para(["Директор Соко", "лова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    text = " ".join(docx.paragraph_texts(dst))
    assert "Соколова" not in text
    assert "{{PERSON_1}}" in text
    assert "Директор" in text


def test_unchanged_paragraph_keeps_its_runs(tmp_path):
    """Абзац без ПД не переписываем - оформление внутри него цело."""
    from pii_mask.core import Masker

    src = _docx(tmp_path / "c.docx",
                [_para(["Итого по ", "накладной"], bold_first=True),
                 _para(["Директор Соколова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    body = zipfile.ZipFile(dst).read("word/document.xml").decode("utf-8")
    assert "<w:b/>" in body, "жирное начертание потеряно"
    assert body.count("Итого по ") == 1 and "накладной" in body


def test_document_stays_a_valid_package(tmp_path):
    from pii_mask.core import Masker

    src = _docx(tmp_path / "d.docx", [_para(["Соколова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        assert "[Content_Types].xml" in z.namelist()
        assert "_rels/.rels" in z.namelist()


def test_header_and_footer_are_masked(tmp_path):
    """Реквизиты в бланке живут в колонтитуле, а не в теле документа."""
    from pii_mask.core import Masker

    header = (f'<?xml version="1.0"?><w:hdr {NS}>'
              f'{_para(["ООО «Ромашка»"])}</w:hdr>')
    src = _docx(tmp_path / "e.docx", [_para(["Товар"])],
                extra={"word/header1.xml": header})
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("ORG",)))
    body = zipfile.ZipFile(dst).read("word/header1.xml").decode("utf-8")
    assert "Ромашка" not in body


def test_unknown_text_part_refuses(tmp_path):
    """Надпись или диаграмма, которую мы не разбираем, - отказ, а не пропуск."""
    from pii_mask.core import Masker

    drawing = ('<?xml version="1.0"?><wp:chart xmlns:wp="x" xmlns:a="y">'
               '<a:t>ООО «Ромашка»</a:t></wp:chart>')
    src = _docx(tmp_path / "f.docx", [_para(["Товар"])],
                extra={"word/charts/chart1.xml": drawing})
    with pytest.raises(ValueError, match="chart"):
        docx.mask_document(src, tmp_path / "o.docx", Masker(types=("ORG",)))


def test_author_is_cleared(tmp_path):
    from pii_mask.core import Masker

    core = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="c" xmlns:dc="d">'
            '<dc:creator>Соколов Иван</dc:creator></cp:coreProperties>')
    src = _docx(tmp_path / "g.docx", [_para(["Товар"])],
                extra={"docProps/core.xml": core})
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    body = zipfile.ZipFile(dst).read("docProps/core.xml").decode("utf-8")
    assert "Соколов" not in body


def test_refuses_to_write_over_source(tmp_path):
    src = _docx(tmp_path / "h.docx", [_para(["Соколова Анна Владимировна"])])
    before = src.read_bytes()
    with pytest.raises(ValueError):
        docx.rewrite(src, src, ["что-то"])
    assert src.read_bytes() == before
