"""Маскировка презентации PowerPoint: текст меняется, слайды остаются.

Текст в pptx лежит так же, как в Word: абзац <a:p> из прогонов <a:t>, и имя
бывает разорвано форматированием. Единица работы - строка абзаца: разрыв
<a:br/> делит абзац на строки и должен остаться на месте.
"""
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats.powerpoint import pptx

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def _para(runs: list[str], bold_first: bool = False) -> str:
    """Абзац из нескольких прогонов - так PowerPoint и хранит текст."""
    out = []
    for i, r in enumerate(runs):
        props = '<a:rPr lang="ru-RU" b="1"/>' if (bold_first and i == 0) else '<a:rPr lang="ru-RU"/>'
        out.append(f"<a:r>{props}<a:t>{r}</a:t></a:r>")
    return f"<a:p>{''.join(out)}</a:p>"


def _shape(paragraphs: list[str], descr: str = "") -> str:
    alt = f' descr="{descr}"' if descr else ""
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Текст 1"{alt}/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f"<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{''.join(paragraphs)}</p:txBody></p:sp>")


def _slide(body: str, root: str = "p:sld") -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><{root} {NS}><p:cSld><p:spTree>'
            f"<p:nvGrpSpPr/><p:grpSpPr/>{body}</p:spTree></p:cSld></{root}>")


def _pptx(path, slides: list[str], extra: dict[str, str | bytes] | None = None,
          order: list[int] | None = None):
    """Презентация из готовых слайдов; order - порядок показа (номера файлов слайдов)."""
    order = order or list(range(1, len(slides) + 1))
    ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order)
    pres = (f'<?xml version="1.0" encoding="UTF-8"?><p:presentation {NS}>'
            f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
    rels = "".join(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/'
                   f'officeDocument/2006/relationships/slide" Target="slides/slide{n}.xml"/>'
                   for n in range(1, len(slides) + 1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels",
                   f'<?xml version="1.0"?><Relationships xmlns="r">{rels}</Relationships>')
        for n, slide in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{n}.xml", slide)
        for name, blob in (extra or {}).items():
            z.writestr(name, blob)
    return path


def _masked(tmp_path, slides: list[str], types: tuple[str, ...], extra=None, **kw):
    src = _pptx(tmp_path / "in.pptx", slides, extra)
    dst = tmp_path / "out.pptx"
    mapping = pptx.mask_presentation(src, dst, Masker(types=types, **kw))
    return dst, mapping


def _part(path, name: str) -> str:
    return zipfile.ZipFile(path).read(name).decode("utf-8")


def test_reads_paragraph_as_whole(tmp_path):
    """Абзац из кусков читается одной строкой - иначе имя не найти."""
    src = _pptx(tmp_path / "a.pptx", [_slide(_shape([_para(["Соко", "лова Анна ", "Владимировна"])]))])
    assert pptx.paragraph_texts(src) == ["Соколова Анна Владимировна"]


def test_masks_name_split_across_runs(tmp_path):
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Докладчик Соко", "лова Анна Владимировна"])]))],
                     ("PERSON",))
    text = " ".join(pptx.paragraph_texts(dst))
    assert "Соколова" not in text
    assert "{{PERSON_1}}" in text
    assert "Докладчик" in text


def test_line_break_stays_between_lines(tmp_path):
    """<a:br/> делит абзац на строки: каждая маскируется на своем месте, разрыв цел."""
    para = ("<a:p><a:r><a:t>Докладчик:</a:t></a:r><a:br/>"
            "<a:r><a:t>Соколова Анна Владимировна</a:t></a:r></a:p>")
    src = _pptx(tmp_path / "b.pptx", [_slide(_shape([para]))])
    assert pptx.paragraph_texts(src) == ["Докладчик:", "Соколова Анна Владимировна"]
    dst = tmp_path / "out.pptx"
    pptx.mask_presentation(src, dst, Masker(types=("PERSON",)))
    body = _part(dst, "ppt/slides/slide1.xml")
    assert "<a:t>Докладчик:</a:t></a:r><a:br/><a:r><a:t>{{PERSON_1}}</a:t>" in body


def test_unchanged_paragraph_keeps_its_runs(tmp_path):
    """Абзац без ПД не переписываем - оформление внутри него цело."""
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Итоги ", "квартала"], bold_first=True),
                                                _para(["Соколова Анна Владимировна"])]))],
                     ("PERSON",))
    body = _part(dst, "ppt/slides/slide1.xml")
    assert 'b="1"' in body, "жирное начертание потеряно"
    assert "<a:t>Итоги </a:t>" in body and "<a:t>квартала</a:t>" in body


def test_masked_presentation_is_well_formed(tmp_path):
    """Каждая XML-часть результата разбирается, архив цел."""
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["ООО «Ромашка» &amp; партнеры &lt;тест&gt;"])]))],
                     ("ORG",), ner=False)
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                ET.fromstring(z.read(name))
    assert "Ромашка" not in _part(dst, "ppt/slides/slide1.xml")


def test_slide_order_follows_presentation(tmp_path):
    """Нумерация меток идет по порядку показа, а не по номерам файлов."""
    slides = [_slide(_shape([_para(["Почта first@example.ru"])])),
              _slide(_shape([_para(["Почта second@example.ru"])]))]
    src = _pptx(tmp_path / "o.pptx", slides, order=[2, 1])
    assert pptx.paragraph_texts(src) == ["Почта second@example.ru", "Почта first@example.ru"]
    mapping = pptx.mask_presentation(src, tmp_path / "out.pptx", Masker(types=("EMAIL",), ner=False))
    assert mapping["labels"]["user1@example.com"]["original"] == "second@example.ru"


def test_notes_and_layout_are_masked(tmp_path):
    notes = _slide(_shape([_para(["Напомнить sokolova@example.ru"])]), root="p:notes")
    layout = _slide(_shape([_para(["Контакт: ivanov@example.ru"])]), root="p:sldLayout")
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Итоги"])]))], ("EMAIL",),
                     {"ppt/notesSlides/notesSlide1.xml": notes,
                      "ppt/slideLayouts/slideLayout1.xml": layout}, ner=False)
    assert "sokolova@example.ru" not in _part(dst, "ppt/notesSlides/notesSlide1.xml")
    assert "ivanov@example.ru" not in _part(dst, "ppt/slideLayouts/slideLayout1.xml")


def test_field_text_is_not_overwritten(tmp_path):
    """Текст поля (номер слайда) PowerPoint пересчитывает сам: маска туда не пишется."""
    para = ('<a:p><a:fld id="{1}" type="slidenum"><a:t>3</a:t></a:fld>'
            "<a:r><a:t> - пишите на sokolova@example.ru</a:t></a:r></a:p>")
    dst, _ = _masked(tmp_path, [_slide(_shape([para]))], ("EMAIL",), ner=False)
    body = _part(dst, "ppt/slides/slide1.xml")
    assert 'type="slidenum"><a:t>3</a:t></a:fld>' in body
    assert "sokolova@example.ru" not in body and "user1@example.com" in body


def test_strict_inn_masks_labelled_table_cell(tmp_path):
    """Подпись "ИНН" в соседней ячейке таблицы слайда: строгий режим не теряет номер."""
    cell = "<a:tc><a:txBody><a:bodyPr/>{}</a:txBody></a:tc>"
    table = ('<p:graphicFrame><a:graphic><a:graphicData><a:tbl><a:tr h="1">'
             + cell.format(_para(["ИНН"])) + cell.format(_para(["6083778353"]))
             + "</a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>")
    dst, _ = _masked(tmp_path, [_slide(table + _shape([_para(["1063391630"])]))], ("INN",),
                     inn_needs_label=True)
    out = pptx.paragraph_texts(dst)
    assert "6083778353" not in out, "ИНН рядом с подписью утек"
    assert "1063391630" in out, "одинокий номер без подписи маскировать не надо"


def test_external_link_target_is_masked(tmp_path):
    rels = ('<?xml version="1.0"?><Relationships xmlns="r">'
            '<Relationship Id="rId1" Type="t/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="t/hyperlink" Target="mailto:sokolova@example.ru"'
            ' TargetMode="External"/></Relationships>')
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Написать"])]))], ("EMAIL",),
                     {"ppt/slides/_rels/slide1.xml.rels": rels}, ner=False)
    body = _part(dst, "ppt/slides/_rels/slide1.xml.rels")
    assert "sokolova@example.ru" not in body
    assert 'Target="../slideLayouts/slideLayout1.xml"' in body, "внутренние связи не трогаем"


def test_alt_text_is_masked(tmp_path):
    """Замещающий текст картинки - атрибут descr, его тоже видно при открытии файла."""
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Фото"])], descr="Почта sokolova@example.ru"))],
                     ("EMAIL",), ner=False)
    body = _part(dst, "ppt/slides/slide1.xml")
    assert "sokolova@example.ru" not in body and 'descr="Почта user1@example.com"' in body


def test_comments_and_authors_are_masked(tmp_path):
    comment = (f'<?xml version="1.0"?><p:cmLst {NS}><p:cm authorId="0">'
               "<p:text>Уточнить у sokolova@example.ru</p:text></p:cm></p:cmLst>")
    authors = (f'<?xml version="1.0"?><p:cmAuthorLst {NS}>'
               '<p:cmAuthor id="0" name="Соколова Анна" initials="СА" lastIdx="1" clrIdx="0"/>'
               "</p:cmAuthorLst>")
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Итоги"])]))], ("EMAIL",),
                     {"ppt/comments/comment1.xml": comment,
                      "ppt/commentAuthors.xml": authors}, ner=False)
    assert "<p:text>Уточнить у user1@example.com</p:text>" in _part(dst, "ppt/comments/comment1.xml")
    body = _part(dst, "ppt/commentAuthors.xml")
    assert "Соколова" not in body and 'initials=""' in body


def test_slide_titles_in_properties_are_cleared(tmp_path):
    """Свойства файла хранят копию заголовков слайдов."""
    app = ('<?xml version="1.0"?><Properties xmlns="a" xmlns:vt="v"><Company>ООО «Ромашка»</Company>'
           '<TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>Отчет Соколовой</vt:lpstr>'
           "</vt:vector></TitlesOfParts><Slides>1</Slides></Properties>")
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Итоги"])]))], ("PERSON",),
                     {"docProps/app.xml": app}, ner=False)
    body = _part(dst, "docProps/app.xml")
    assert "Соколов" not in body and "Ромашка" not in body
    assert "<Slides>1</Slides>" in body


@pytest.mark.parametrize("name", ["ppt/embeddings/oleObject1.bin",
                                  "ppt/embeddings/Microsoft_Word_Document.docx"])
def test_embedded_object_refuses(tmp_path, name):
    """Вложенный объект (не книга диаграммы): его превью-картинка покажет оригинал - отказ."""
    with pytest.raises(ValueError, match="embeddings"):
        _masked(tmp_path, [_slide(_shape([_para(["Итоги"])]))], ("PERSON",),
                {name: b"PK\x03\x04binary"}, ner=False)


def _chart_deck(tmp_path, book_values: list[str]):
    """Презентация с диаграммой, у которой своя книга с данными."""
    from test_xlsx import _book

    (tmp_path / "book").mkdir()
    book = _book(tmp_path / "book", book_values).read_bytes()
    chart = ('<?xml version="1.0"?><c:chartSpace xmlns:c="c" xmlns:a="a" xmlns:r="r"><c:chart><c:ser>'
             '<c:tx><c:strRef><c:f>Лист1!$A$1</c:f><c:strCache><c:pt idx="0">'
             "<c:v>Почта sokolova@example.ru</c:v></c:pt></c:strCache></c:strRef></c:tx></c:ser>"
             '</c:chart><c:externalData r:id="rId1"/></c:chartSpace>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="r"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" '
            'Target="../embeddings/Microsoft_Excel_Worksheet.xlsx"/></Relationships>')
    return _pptx(tmp_path / "chart.pptx", [_slide(_shape([_para(["Итоги"])]))],
                 {"ppt/charts/chart1.xml": chart, "ppt/charts/_rels/chart1.xml.rels": rels,
                  "ppt/embeddings/Microsoft_Excel_Worksheet.xlsx": book})


def _embedded_texts(path, tmp_path) -> list[str]:
    from pii_mask_enhanced.formats.excel import xlsx

    book = tmp_path / "inner.xlsx"
    book.write_bytes(zipfile.ZipFile(path).read("ppt/embeddings/Microsoft_Excel_Worksheet.xlsx"))
    return xlsx.cell_texts(book)


def test_chart_and_its_workbook_are_masked(tmp_path):
    """Кэш диаграммы и книга с ее данными («Изменить данные») - под одной меткой."""
    src = _chart_deck(tmp_path, ["Почта sokolova@example.ru"])
    dst = tmp_path / "out.pptx"
    mapping = pptx.mask_presentation(src, dst, Masker(types=("EMAIL",), ner=False))
    assert "sokolova@example.ru" not in _part(dst, "ppt/charts/chart1.xml")
    assert "<c:v>Почта user1@example.com</c:v>" in _part(dst, "ppt/charts/chart1.xml")
    assert "Почта user1@example.com" in _embedded_texts(dst, tmp_path)
    assert len(mapping["labels"]) == 1

    restored = tmp_path / "restored.pptx"
    pptx.unmask_presentation(dst, restored, mapping)
    assert "<c:v>Почта sokolova@example.ru</c:v>" in _part(restored, "ppt/charts/chart1.xml")
    assert "Почта sokolova@example.ru" in _embedded_texts(restored, tmp_path)


def test_smartart_text_is_masked(tmp_path):
    para = "<a:p><a:r><a:t>Пишите на sokolova@example.ru</a:t></a:r></a:p>"
    extra = {"ppt/diagrams/data1.xml": f'<?xml version="1.0"?><dgm:dataModel xmlns:dgm="d" {NS}>{para}</dgm:dataModel>',
             "ppt/diagrams/drawing1.xml": f'<?xml version="1.0"?><dsp:drawing xmlns:dsp="s" {NS}>{para}</dsp:drawing>'}
    dst, _ = _masked(tmp_path, [_slide(_shape([_para(["Итоги"])]))], ("EMAIL",), extra, ner=False)
    for name in extra:
        assert "<a:t>Пишите на user1@example.com</a:t>" in _part(dst, name)


def test_text_outside_paragraph_refuses(tmp_path):
    src = _pptx(tmp_path / "x.pptx", [_slide("<a:t>Соколова</a:t>")])
    with pytest.raises(ValueError, match="вне абзаца"):
        pptx.mask_presentation(src, tmp_path / "out.pptx", Masker(types=("PERSON",), ner=False))


def test_refuses_to_write_over_source(tmp_path):
    src = _pptx(tmp_path / "s.pptx", [_slide(_shape([_para(["Итоги"])]))])
    with pytest.raises(ValueError, match="поверх"):
        pptx.mask_presentation(src, src, Masker(types=("PERSON",), ner=False))


def test_unmask_presentation_restores_text(tmp_path):
    """mask -> unmask возвращает презентацию с тем же текстом."""
    slides = [_slide(_shape([_para(["Докладчик Соко", "лова Анна Владимировна"]), _para(["Итоги"])],
                            descr="Почта sokolova@example.ru"))]
    src = _pptx(tmp_path / "u.pptx", slides)
    masked = tmp_path / "u.masked.pptx"
    mapping = pptx.mask_presentation(src, masked, Masker(types=("PERSON", "EMAIL")))
    restored = tmp_path / "u.unmasked.pptx"
    pptx.unmask_presentation(masked, restored, mapping)
    assert pptx.paragraph_texts(restored) == pptx.paragraph_texts(src)


def _run_cli(argv):
    from pii_mask_enhanced.cli.cli import main

    old, sys.argv = sys.argv, ["pii-mask", *argv]
    try:
        with pytest.raises(SystemExit) as exit_info:
            main()
    finally:
        sys.argv = old
    return exit_info.value.code


def test_cli_masks_and_unmasks_pptx(tmp_path):
    """Сквозной путь: .pptx -> .masked.pptx и реестр -> .unmasked.pptx."""
    src = _pptx(tmp_path / "отчет.pptx", [_slide(_shape([_para(["Почта sokolova@example.ru"])]))])
    assert _run_cli(["mask", str(src), "--types", "EMAIL", "--no-ner"]) == 0
    masked = tmp_path / "отчет.masked.pptx"
    assert pptx.paragraph_texts(masked) == ["Почта user1@example.com"]
    mp = tmp_path / "отчет.mapping.json"
    assert json.loads(mp.read_text(encoding="utf-8"))["labels"]
    assert _run_cli(["unmask", str(masked), "--mapping", str(mp)]) == 0
    assert pptx.paragraph_texts(tmp_path / "отчет.unmasked.pptx") == ["Почта sokolova@example.ru"]
