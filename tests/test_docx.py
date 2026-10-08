"""Маскировка документа Word: текст меняется, оформление остается.

Word рвет фразу на куски по форматированию и следам правки: "Иванов" в файле
запросто лежит двумя узлами - "Иван" и "ов". Поэтому единица работы - абзац
целиком, а не отдельный узел: иначе распознаватель не увидит ни одного имени.
"""
import zipfile

import pytest

from pii_mask_enhanced.formats import docx

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
    from pii_mask_enhanced.engine.core import Masker

    src = _docx(tmp_path / "b.docx", [_para(["Директор Соко", "лова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    text = " ".join(docx.paragraph_texts(dst))
    assert "Соколова" not in text
    assert "{{PERSON_1}}" in text
    assert "Директор" in text


def test_unchanged_paragraph_keeps_its_runs(tmp_path):
    """Абзац без ПД не переписываем - оформление внутри него цело."""
    from pii_mask_enhanced.engine.core import Masker

    src = _docx(tmp_path / "c.docx",
                [_para(["Итого по ", "накладной"], bold_first=True),
                 _para(["Директор Соколова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    body = zipfile.ZipFile(dst).read("word/document.xml").decode("utf-8")
    assert "<w:b/>" in body, "жирное начертание потеряно"
    assert body.count("Итого по ") == 1 and "накладной" in body


def test_document_stays_a_valid_package(tmp_path):
    from pii_mask_enhanced.engine.core import Masker

    src = _docx(tmp_path / "d.docx", [_para(["Соколова Анна Владимировна"])])
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=("PERSON",)))
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        assert "[Content_Types].xml" in z.namelist()
        assert "_rels/.rels" in z.namelist()


def test_header_and_footer_are_masked(tmp_path):
    """Реквизиты в бланке живут в колонтитуле, а не в теле документа."""
    from pii_mask_enhanced.engine.core import Masker

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
    from pii_mask_enhanced.engine.core import Masker

    drawing = ('<?xml version="1.0"?><wp:chart xmlns:wp="x" xmlns:a="y">'
               '<a:t>ООО «Ромашка»</a:t></wp:chart>')
    src = _docx(tmp_path / "f.docx", [_para(["Товар"])],
                extra={"word/charts/chart1.xml": drawing})
    with pytest.raises(ValueError, match="chart"):
        docx.mask_document(src, tmp_path / "o.docx", Masker(types=("ORG",)))


def test_author_is_cleared(tmp_path):
    from pii_mask_enhanced.engine.core import Masker

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


# --- утечки: текст, который раньше проходил мимо маскировки ---

def _textbox(inner: str) -> str:
    """Надпись внутри прогона: в ней свои абзацы, вложенные во внешний."""
    return f"<w:r><w:pict><w:txbxContent>{inner}</w:txbxContent></w:pict></w:r>"


def _masked_body(tmp_path, paragraphs, types, extra=None, part="word/document.xml"):
    from pii_mask_enhanced.engine.core import Masker

    src = _docx(tmp_path / "src.docx", paragraphs, extra)
    dst = tmp_path / "out.docx"
    docx.mask_document(src, dst, Masker(types=types))
    return zipfile.ZipFile(dst).read(part).decode("utf-8")


def test_text_after_textbox_is_masked(tmp_path):
    """Вложенный абзац надписи не обрывает внешний: текст после надписи тоже маскируется."""
    para = ("<w:p><w:r><w:t>Договор. </w:t></w:r>"
            + _textbox(_para(["Приложение"]))
            + "<w:r><w:t>Директор Соколова Анна Владимировна</w:t></w:r></w:p>")
    body = _masked_body(tmp_path, [para], ("PERSON",))
    assert "Соколова" not in body
    assert "Приложение" in body


def test_text_inside_textbox_is_masked(tmp_path):
    para = ("<w:p><w:r><w:t>Договор</w:t></w:r>"
            + _textbox(_para(["Директор Соколова Анна Владимировна"])) + "</w:p>")
    body = _masked_body(tmp_path, [para], ("PERSON",))
    assert "Соколова" not in body
    assert "Договор" in body


def test_deleted_revision_text_is_masked(tmp_path):
    """Удаленный при рецензировании текст лежит в файле и виден при отклонении правки."""
    para = ('<w:p><w:r><w:t>Договор</w:t></w:r><w:del w:id="1" w:author="x">'
            "<w:r><w:delText>Директор Соколова Анна Владимировна</w:delText></w:r>"
            "</w:del></w:p>")
    body = _masked_body(tmp_path, [para], ("PERSON",))
    assert "Соколова" not in body
    assert "<w:delText" in body, "удаленный текст должен остаться удаленным"


def test_field_code_is_masked(tmp_path):
    """Адрес в коде поля HYPERLINK - тот же e-mail, что и в тексте ссылки."""
    para = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:</w:instrText></w:r>'
            '<w:r><w:instrText>sokolova@example.ru" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>написать</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    body = _masked_body(tmp_path, [para], ("EMAIL",))
    assert "sokolova@example.ru" not in body
    assert "HYPERLINK" in body


def test_other_field_in_paragraph_is_untouched(tmp_path):
    """Коды разных полей не склеиваются: поле без ПД остается как было."""
    para = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> PAGE </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> HYPERLINK "mailto:sokolova@example.ru" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    body = _masked_body(tmp_path, [para], ("EMAIL",))
    assert "<w:instrText> PAGE </w:instrText>" in body
    assert "sokolova@example.ru" not in body


def test_revision_and_comment_authors_are_cleared(tmp_path):
    import xml.etree.ElementTree as ET

    para = ('<w:p><w:ins w:id="1" w:author="Соколова Анна" w:date="2026-01-01T00:00:00Z">'
            "<w:r><w:t>Товар</w:t></w:r></w:ins></w:p>")
    comments = (f'<?xml version="1.0"?><w:comments {NS}>'
                 '<w:comment w:id="0" w:author="Соколова Анна" w:initials="СА">'
                 f'{_para(["Проверить"])}</w:comment></w:comments>')
    people = ('<?xml version="1.0"?><w15:people xmlns:w15="p">'
              '<w15:person w15:author="Соколова Анна"><w15:presenceInfo w15:providerId="AD"'
              ' w15:userId="S::sokolova@example.ru::1"/></w15:person></w15:people>')
    extra = {"word/comments.xml": comments, "word/people.xml": people}
    for part in ("word/document.xml", "word/comments.xml", "word/people.xml"):
        body = _masked_body(tmp_path, [para], ("PERSON",), extra, part)
        assert "Соколова" not in body and "sokolova" not in body, part
        assert 'w:initials="СА"' not in body, part
        ET.fromstring(body.encode("utf-8"))      # атрибут опустошен, а не сломан


def test_text_outside_paragraph_refuses(tmp_path):
    """Текст вне абзаца мы не разбираем - отказ, а не тихий пропуск."""
    from pii_mask_enhanced.engine.core import Masker

    src = _docx(tmp_path / "i.docx", [_para(["Товар"]), "<w:r><w:t>Соколова Анна</w:t></w:r>"])
    with pytest.raises(ValueError, match="вне абзаца"):
        docx.mask_document(src, tmp_path / "o.docx", Masker(types=("PERSON",)))


def test_self_closing_tags_do_not_swallow_text(tmp_path):
    """<w:p .../> и <w:t .../> пустые: они не открывают абзац или узел до следующего закрытия."""
    src = _docx(tmp_path / "j.docx",
                ['<w:p w:rsidR="00A1"/>',
                 '<w:p><w:r><w:t xml:space="preserve"/></w:r><w:r><w:t>Товар</w:t></w:r></w:p>'])
    assert docx.paragraph_texts(src) == ["Товар"]


def test_external_link_target_is_masked(tmp_path):
    """Адрес ссылки хранится в связях части, а не в тексте документа."""
    rels = ('<?xml version="1.0"?><Relationships xmlns="r">'
            '<Relationship Id="rId1" Type="t/styles" Target="styles.xml"/>'
            '<Relationship Id="rId2" Type="t/hyperlink" Target="mailto:sokolova@example.ru"'
            ' TargetMode="External"/></Relationships>')
    body = _masked_body(tmp_path, [_para(["Товар"])], ("EMAIL",),
                        {"word/_rels/document.xml.rels": rels}, "word/_rels/document.xml.rels")
    assert "sokolova@example.ru" not in body
    assert 'Target="mailto:' in body and 'TargetMode="External"' in body
    assert 'Target="styles.xml"' in body, "внутренние связи не трогаем"


def test_simple_field_code_is_masked(tmp_path):
    """Короткая запись поля держит код в атрибуте w:instr."""
    import xml.etree.ElementTree as ET

    para = ('<w:p><w:fldSimple w:instr=" HYPERLINK &quot;mailto:sokolova@example.ru&quot; ">'
            "<w:r><w:t>написать</w:t></w:r></w:fldSimple></w:p>")
    body = _masked_body(tmp_path, [para], ("EMAIL",))
    assert "sokolova@example.ru" not in body
    assert "HYPERLINK &quot;mailto:" in body
    ET.fromstring(body.encode("utf-8"))     # атрибут остался корректным XML


def test_document_properties_are_cleared(tmp_path):
    core = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="c" xmlns:dc="d">'
            "<dc:title>Договор с Соколовой Анной</dc:title><dc:subject>Соколова</dc:subject>"
            "<dc:description>Соколова</dc:description><cp:keywords>Соколова</cp:keywords>"
            "<cp:category>Соколова</cp:category></cp:coreProperties>")
    app = ('<?xml version="1.0"?><Properties xmlns="a"><Company>ООО «Ромашка»</Company>'
           "<Manager>Соколова Анна</Manager><Pages>1</Pages></Properties>")
    extra = {"docProps/core.xml": core, "docProps/app.xml": app}
    assert "Соколов" not in _masked_body(tmp_path, [_para(["Товар"])], ("PERSON",),
                                         extra, "docProps/core.xml")
    body = _masked_body(tmp_path, [_para(["Товар"])], ("PERSON",), extra, "docProps/app.xml")
    assert "Ромашка" not in body and "Соколова" not in body
    assert "<Pages>1</Pages>" in body
