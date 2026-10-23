"""Маскировка книги Excel: текст ячеек меняется, структура книги остается живой.

Фикстуры синтетические. Настоящие книги 1С кладут текст двумя разными способами
(общая таблица строк и инлайн прямо в листе), поэтому оба покрыты здесь.
"""
import zipfile

import pytest

from pii_mask_enhanced.formats.excel import xlsx
from pii_mask_enhanced.formats.excel.xlsx import XLSX

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheets><sheet name="Лист1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>
</workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""


def _book(tmp_path, shared: list[str], inline: list[str] = (), numbers: list[str] = ()):
    """Собрать минимальную, но настоящую книгу: общие строки + инлайн + числа."""
    path = tmp_path / "book.xlsx"
    si = "".join(f"<si><t>{s}</t></si>" for s in shared)
    sst = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
           f'count="{len(shared)}" uniqueCount="{len(shared)}">{si}</sst>')
    cells = "".join(f'<c r="A{i+1}" t="s"><v>{i}</v></c>' for i in range(len(shared)))
    cells += "".join(f'<c r="B{i+1}" t="inlineStr"><is><t>{s}</t></is></c>'
                     for i, s in enumerate(inline))
    cells += "".join(f'<c r="C{i+1}"><v>{n}</v></c>' for i, n in enumerate(numbers))
    sheet = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData><row>{cells}</row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def test_reads_shared_and_inline_strings(tmp_path):
    src = _book(tmp_path, shared=["ООО «Ромашка»", "Контрагент"], inline=["Петров Иван"])
    assert XLSX.texts(src) == ["ООО «Ромашка»", "Контрагент", "Петров Иван"]


def test_numbers_are_read_and_plain_ones_stay_numbers(tmp_path):
    """Число - тоже значение книги: ИНН и СНИЛС, набранные без пробелов, Excel хранит
    числом. Число без ПД (количество, сумма в счете) остается числовой ячейкой."""
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["Доход"], numbers=["1000", "45678"])
    assert XLSX.texts(src) == ["Доход", "1000", "45678"]
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(ner=False))
    sheet = zipfile.ZipFile(dst).read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="C1"><v>1000</v></c>' in sheet


def test_rewrite_replaces_text_and_keeps_workbook_valid(tmp_path):
    src = _book(tmp_path, shared=["ООО «Ромашка»", "Контрагент"], inline=["Петров Иван"])
    dst = tmp_path / "out.xlsx"
    XLSX.rewrite(src, dst, ["{{ORG_1}}", "Контрагент", "{{PERSON_1}}"])
    assert XLSX.texts(dst) == ["{{ORG_1}}", "Контрагент", "{{PERSON_1}}"]
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        # части книги не потеряны - иначе Excel откажется открывать
        assert "xl/workbook.xml" in z.namelist()
        assert "[Content_Types].xml" in z.namelist()


def test_rewrite_rejects_length_mismatch(tmp_path):
    """Рассинхрон списка значений - это сдвиг подстановки по всей книге."""
    src = _book(tmp_path, shared=["а", "б"])
    with pytest.raises(ValueError):
        XLSX.rewrite(src, tmp_path / "out.xlsx", ["только одно"])


def test_special_chars_survive_roundtrip(tmp_path):
    """Кавычки и амперсанд в названии - обычное дело у контрагентов."""
    src = _book(tmp_path, shared=['ООО "Р&Д" <тест>'])
    dst = tmp_path / "out.xlsx"
    XLSX.rewrite(src, dst, ['ЗАО "А&Б" <x>'])
    assert XLSX.texts(dst) == ['ЗАО "А&Б" <x>']


def test_mask_workbook_masks_org_keeps_numbers(tmp_path):
    """Сквозной путь: книга на входе - книга на выходе, реестр общий на всю книгу."""
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «Ромашка»", "Содержание операции", "ООО «Ромашка»"],
                numbers=["1000"])
    dst = tmp_path / "out.xlsx"
    mapping = XLSX.mask(src, dst, Masker(types=("ORG", "PERSON")))
    out = XLSX.texts(dst)
    assert "ООО «Ромашка»" not in out
    assert "Содержание операции" in out          # канцелярия не ПД
    # одна сущность, встреченная дважды, получает одну метку на всю книгу
    assert out[0] == out[2]
    assert len([r for r in mapping["labels"].values() if r["type"] == "ORG"]) == 1


def test_multiline_cell_survives(tmp_path):
    """Alt+Enter в ячейке - обычное дело; склейка через \\n не должна разъезжаться."""
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «Ромашка»\nвторая строка", "Итого"])
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(types=("ORG",)))
    out = XLSX.texts(dst)
    assert len(out) == 2
    assert out[1] == "Итого"
    assert "ООО «Ромашка»" not in out[0]
    assert out[0].endswith("\nвторая строка")   # структура ячейки цела


def test_numeric_char_refs_decoded(tmp_path):
    """&#10; - это то, как Excel хранит перевод строки внутри ячейки.

    Наивный unescape их не знает: читает как литерал, а при записи ещё и
    экранирует амперсанд - текст ячейки меняется на глазах у пользователя.
    """
    src = _book(tmp_path, shared=["one&#10;two", "x&#38;y", "a&amp;b"])
    assert XLSX.texts(src) == ["one\ntwo", "x&y", "a&b"]


def test_escaped_reference_is_not_decoded_twice(tmp_path):
    """&amp;#10; означает литерал "&#10;", а не перевод строки."""
    src = _book(tmp_path, shared=["a&amp;#10;b"])
    assert XLSX.texts(src) == ["a&#10;b"]


def test_roundtrip_preserves_reference_text(tmp_path):
    src = _book(tmp_path, shared=["one&#10;two"])
    dst = tmp_path / "out.xlsx"
    XLSX.rewrite(src, dst, XLSX.texts(src))
    assert XLSX.texts(dst) == ["one\ntwo"]


def test_carriage_return_survives(tmp_path):
    """Сырой \\r XML-парсер нормализует в \\n - его надо писать ссылкой."""
    src = _book(tmp_path, shared=["a"])
    dst = tmp_path / "out.xlsx"
    XLSX.rewrite(src, dst, ["строка\r\nвторая"])
    assert XLSX.texts(dst) == ["строка\r\nвторая"]


# --- находки состязательного ревью ---

def test_refuses_to_write_over_source(tmp_path):
    """src == dst обнулял книгу до первого чтения: 22 КБ превращались в 22 байта."""
    src = _book(tmp_path, shared=["ООО «Ромашка»"])
    before = src.read_bytes()
    with pytest.raises(ValueError):
        XLSX.rewrite(src, src, ["{{ORG_1}}"])
    assert src.read_bytes() == before, "исходник должен остаться нетронутым"


def test_entity_swallowing_newline_does_not_break_book(tmp_path):
    """Распознаватель склеивает название через перенос - число строк меняется.

    Схема "склеить всё и разрезать обратно" на этом ломалась. Поячеечная
    маскировка к длине строк не привязана.
    """
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «СТРОЙМОНТАЖНАЛАДКА\nСТРОЙ»", "Итого"])
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(types=("ORG",), ner=False))
    out = XLSX.texts(dst)
    assert len(out) == 2 and out[1] == "Итого"
    assert "СТРОЙМОНТАЖНАЛАДКА" not in out[0]


def test_namespaced_tags_are_found(tmp_path):
    """<x:si> - валидный OOXML. Раньше давал ноль ячеек, и ПД шли насквозь."""
    path = tmp_path / "ns.xlsx"
    sst = ('<?xml version="1.0"?><x:sst xmlns:x="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main"><x:si><x:t>ООО «Ромашка»</x:t></x:si></x:sst>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
    assert XLSX.texts(path) == ["ООО «Ромашка»"]


def test_nonstandard_worksheet_name_is_scanned(tmp_path):
    """Имя части листа задаётся связями, а не обязано быть sheet1.xml."""
    path = tmp_path / "odd.xlsx"
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData><row><c t="inlineStr"><is><t>'
             'ООО «Ромашка»</t></is></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/worksheets/детализация.xml", sheet)
    assert XLSX.texts(path) == ["ООО «Ромашка»"]


def test_unknown_text_part_refuses_instead_of_leaking(tmp_path):
    """Надпись на диаграмме мы обезличивать не умеем - значит не молчим.

    Тихо скопировать часть с текстом = выпустить ПД наружу без единой ошибки.
    """
    from pii_mask_enhanced.engine.core import Masker

    path = tmp_path / "draw.xlsx"
    unknown = ('<?xml version="1.0"?><x:custom xmlns:x="x" xmlns:a="y">'
               '<a:p><a:r><a:t>ООО «Ромашка»</a:t></a:r></a:p></x:custom>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst><si><t>Итого</t></si></sst>')
        z.writestr("xl/custom/item1.xml", unknown)
    with pytest.raises(ValueError, match="custom"):
        XLSX.mask(path, tmp_path / "o.xlsx", Masker(types=("ORG",), ner=False))


def _book_with(tmp_path, parts: dict[str, str], shared=("Итого",), workbook=WORKBOOK):
    """Книга _book с дополнительными частями и своим workbook.xml."""
    src = _book(tmp_path, list(shared))
    out = tmp_path / "extra.xlsx"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            blob = workbook.encode("utf-8") if info.filename == "xl/workbook.xml" else zin.read(info)
            zout.writestr(info, blob)
        for name, blob in parts.items():
            zout.writestr(name, blob)
    return out


def _part_text(path, name: str) -> str:
    return zipfile.ZipFile(path).read(name).decode("utf-8")


def test_shape_text_is_masked(tmp_path):
    """Надпись на листе - абзац DrawingML; замещающий текст картинки - тоже."""
    from pii_mask_enhanced.engine.core import Masker

    drawing = ('<?xml version="1.0"?><xdr:wsDr xmlns:xdr="x" xmlns:a="y"><xdr:sp><xdr:nvSpPr>'
               '<xdr:cNvPr id="2" name="Надпись 1" descr="Логотип ООО «Лютик»"/></xdr:nvSpPr>'
               "<xdr:txBody><a:p><a:r><a:t>Подготовил ООО «Ромашка»</a:t></a:r></a:p></xdr:txBody>"
               "</xdr:sp></xdr:wsDr>")
    src = _book_with(tmp_path, {"xl/drawings/drawing1.xml": drawing})
    dst = tmp_path / "o.xlsx"
    mapping = XLSX.mask(src, dst, Masker(types=("ORG",), ner=False))
    body = _part_text(dst, "xl/drawings/drawing1.xml")
    assert "Ромашка" not in body and "Лютик" not in body
    restored = tmp_path / "r.xlsx"
    XLSX.unmask(dst, restored, mapping)
    assert XLSX.texts(restored) == XLSX.texts(src)


def test_chart_cache_is_masked_like_cells(tmp_path):
    from pii_mask_enhanced.engine.core import Masker

    chart = ('<?xml version="1.0"?><c:chartSpace xmlns:c="c"><c:chart><c:ser><c:cat><c:strRef>'
             '<c:f>Лист1!$A$1</c:f><c:strCache><c:pt idx="0"><c:v>ООО «Ромашка»</c:v></c:pt>'
             "</c:strCache></c:strRef></c:cat></c:ser></c:chart></c:chartSpace>")
    src = _book_with(tmp_path, {"xl/charts/chart1.xml": chart}, shared=("ООО «Ромашка»",))
    dst = tmp_path / "o.xlsx"
    XLSX.mask(src, dst, Masker(types=("ORG",), ner=False))
    assert "<c:v>{{ORG_1}}</c:v>" in _part_text(dst, "xl/charts/chart1.xml")
    assert XLSX.texts(dst)[0] == "{{ORG_1}}", "ячейка и кэш диаграммы - одна метка"


def test_pivot_cache_is_masked(tmp_path):
    """Кэш сводной таблицы хранит копию исходных строк в атрибутах."""
    from pii_mask_enhanced.engine.core import Masker

    definition = ('<?xml version="1.0"?><pivotCacheDefinition refreshedBy="Соколова Анна">'
                  '<cacheSource type="worksheet">'
                  '<worksheetSource ref="A1:B3" sheet="Лист1"/></cacheSource><cacheFields>'
                  '<cacheField name="Почта"><sharedItems><s v="sokolova@example.ru"/></sharedItems>'
                  "</cacheField></cacheFields></pivotCacheDefinition>")
    records = ('<?xml version="1.0"?><pivotCacheRecords><r><x v="0"/><s v="ivanov@example.ru"/>'
               '<n v="1500"/></r></pivotCacheRecords>')
    src = _book_with(tmp_path, {"xl/pivotCache/pivotCacheDefinition1.xml": definition,
                                 "xl/pivotCache/pivotCacheRecords1.xml": records})
    dst = tmp_path / "o.xlsx"
    XLSX.mask(src, dst, Masker(types=("EMAIL",), ner=False))
    body = (_part_text(dst, "xl/pivotCache/pivotCacheDefinition1.xml")
            + _part_text(dst, "xl/pivotCache/pivotCacheRecords1.xml"))
    assert "sokolova@" not in body and "ivanov@" not in body
    assert '<x v="0"/>' in body and '<n v="1500"/>' in body and 'name="Почта"' in body
    assert 'refreshedBy=""' in body, "кто обновлял сводную - след автора"


def test_saved_path_and_share_user_are_cleared(tmp_path):
    """Путь, где книгу сохраняли, содержит имя пользователя Windows."""
    from pii_mask_enhanced.engine.core import Masker

    workbook = WORKBOOK.replace(
        "<sheets>", '<fileSharing userName="Соколова Анна"/><x15ac:absPath xmlns:x15ac="x" '
                    'url="C:\\Users\\sokolova\\Documents\\"/><sheets>')
    src = _book_with(tmp_path, {}, workbook=workbook)
    dst = tmp_path / "o.xlsx"
    XLSX.mask(src, dst, Masker(types=("PERSON",), ner=False))
    body = _part_text(dst, "xl/workbook.xml")
    assert "sokolova" not in body and "Соколова" not in body
    assert 'url=""' in body and 'userName=""' in body


def test_sheet_name_with_pii_is_renamed_with_references(tmp_path):
    """Лист "ООО «Ромашка»" - имя маскируется, ссылки на лист в формулах и диаграммах тоже."""
    from pii_mask_enhanced.engine.core import Masker

    workbook = WORKBOOK.replace('name="Лист1"', 'name="ООО «Ромашка»"').replace(
        "</workbook>", "<definedNames><definedName name=\"итог\">'ООО «Ромашка»'!$A$1"
                       "</definedName></definedNames></workbook>")
    chart = ('<?xml version="1.0"?><c:chartSpace xmlns:c="c"><c:chart><c:ser><c:val><c:numRef>'
             "<c:f>'ООО «Ромашка»'!$C$1</c:f></c:numRef></c:val></c:ser></c:chart></c:chartSpace>")
    src = _book_with(tmp_path, {"xl/charts/chart1.xml": chart}, workbook=workbook)
    dst = tmp_path / "o.xlsx"
    mapping = XLSX.mask(src, dst, Masker(types=("ORG",), ner=False))
    assert XLSX.sheet_names(dst) == ["{{ORG_1}}"]
    assert "'{{ORG_1}}'!$A$1</definedName>" in _part_text(dst, "xl/workbook.xml")
    assert "<c:f>'{{ORG_1}}'!$C$1</c:f>" in _part_text(dst, "xl/charts/chart1.xml")

    restored = tmp_path / "r.xlsx"
    XLSX.unmask(dst, restored, mapping)
    assert XLSX.sheet_names(restored) == ["ООО «Ромашка»"]
    assert "<c:f>'ООО «Ромашка»'!$C$1</c:f>" in _part_text(restored, "xl/charts/chart1.xml")


def test_plain_sheet_reference_is_renamed():
    out = xlsx._rename_sheets(b"<f>SUM(Petrov!A1:A3)+Petrov2!B1</f>", {"Petrov": "{{PERSON_1}}"})
    assert out == b"<f>SUM('{{PERSON_1}}'!A1:A3)+Petrov2!B1</f>"


def test_long_masked_sheet_name_becomes_neutral():
    names = ["Отчет", "Ромашка"]
    assert xlsx._new_sheet_names(names, ["Отчет", "{{ORG_1}} и еще очень длинное продолжение"]) == {
        "Ромашка": "Лист2"}


def test_comment_text_and_author_are_masked(tmp_path):
    """Комментарий к ячейке и его автор - такой же канал утечки, как ячейка."""
    from pii_mask_enhanced.engine.core import Masker

    path = tmp_path / "c.xlsx"
    comments = ('<?xml version="1.0"?><comments><authors><author>Петров Иван</author>'
                '</authors><commentList><comment ref="A1" authorId="0"><text><r>'
                '<t>звонил из ООО «Ромашка»</t></r></text></comment></commentList></comments>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst><si><t>Итого</t></si></sst>')
        z.writestr("xl/comments1.xml", comments)
    dst = tmp_path / "o.xlsx"
    XLSX.mask(path, dst, Masker(types=("ORG", "PERSON")))
    body = zipfile.ZipFile(dst).read("xl/comments1.xml").decode("utf-8")
    assert "Ромашка" not in body
    assert "Петров" not in body


def test_document_author_is_cleared(tmp_path):
    """В свойствах файла лежит имя того, кто его сохранил."""
    from pii_mask_enhanced.engine.core import Masker

    path = tmp_path / "p.xlsx"
    core = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="c" xmlns:dc="d">'
            '<dc:creator>Петров Иван</dc:creator>'
            '<cp:lastModifiedBy>Сидорова Анна</cp:lastModifiedBy></cp:coreProperties>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst><si><t>Итого</t></si></sst>')
        z.writestr("docProps/core.xml", core)
    dst = tmp_path / "o.xlsx"
    XLSX.mask(path, dst, Masker(types=("PERSON",)))
    body = zipfile.ZipFile(dst).read("docProps/core.xml").decode("utf-8")
    assert "Петров" not in body and "Сидорова" not in body


def test_unchanged_cell_keeps_rich_text_runs(tmp_path):
    """Ячейку без ПД не переписываем - иначе теряется посимвольное оформление."""
    path = tmp_path / "rich.xlsx"
    sst = ('<?xml version="1.0"?><sst><si><r><t>Ито</t></r><r><t>го</t></r></si></sst>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
    dst = tmp_path / "o.xlsx"
    XLSX.rewrite(path, dst, ["Итого"])          # значение то же самое
    body = zipfile.ZipFile(dst).read("xl/sharedStrings.xml").decode("utf-8")
    assert body.count("<t>") == 2, "раны должны остаться на месте"


def test_workbook_supplies_supported_names(tmp_path):
    """Книга сама объявляет своих контрагентов - ячейкой с правовой формой.

    Без этого строгий режим терял незнакомую словарю фамилию: в книгу уходило
    "ИП Метелина {{PERSON_1}}". Марка товара поддержки не получает - правовой
    формы рядом с ней нет нигде.
    """
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ИП Метелина Лилия Вячеславовна",
                                  "Постфильтр минерализатор Аквабрис",
                                  "ИП Метелина"])
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(types=("PERSON", "ORG"),
                                        ner_org_needs_form=True,
                                        ner_person_needs_fio=True))
    out = XLSX.texts(dst)
    assert "Метелина" not in " ".join(out), "фамилия контрагента утекла"
    assert "Аквабрис" in out[1], "марка товара не должна маскироваться"


def test_supported_names_scans_legal_form_cells(tmp_path):
    src = _book(tmp_path, shared=['ООО "Ромашка"', "ИП Метелина Лилия Вячеславовна",
                                  "Аквабрис"])
    names = XLSX.supported_names(src)
    assert "метелина" in names and "ромашка" in names
    assert "аквабрис" not in names


def _grid_book(path, cells: dict[str, str]):
    """Книга с текстом по координатам: {"A9": "ИНН", "B9": "6083778353"}."""
    sst = ('<?xml version="1.0"?><sst>'
           + "".join(f"<si><t>{text}</t></si>" for text in cells.values()) + "</sst>")
    rows: dict[int, str] = {}
    for i, ref in enumerate(cells):
        row = int("".join(c for c in ref if c.isdigit()))
        rows[row] = rows.get(row, "") + f'<c r="{ref}" t="s"><v>{i}</v></c>'
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             + "".join(f'<row r="{r}">{c}</row>' for r, c in sorted(rows.items()))
             + "</sheetData></worksheet>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def test_strict_inn_masks_labelled_neighbour(tmp_path):
    """Подпись реквизита стоит в СОСЕДНЕЙ ячейке, а не в той же.

    В боевом отчете это A9='ИНН', B9='6083778353'. Маскировка идет по одной
    ячейке и соседей не видит, поэтому строгий режим пропускал настоящий ИНН,
    отсеивая заодно и артикулы. Смотреть надо на таблицу.
    """
    from pii_mask_enhanced.engine.core import Masker

    path = _grid_book(tmp_path / "req.xlsx",
                      {"A9": "ИНН", "B9": "6083778353", "C20": "1063391630"})
    labelled = XLSX.labels(path)
    assert "6083778353" in labelled, "ИНН рядом с подписью должен быть доверенным"
    assert "1063391630" not in labelled, "одинокий артикул подписи не имеет"

    dst = tmp_path / "o.xlsx"
    masker = Masker(types=("INN",), inn_needs_label=True)
    XLSX.mask(path, dst, masker)
    out = XLSX.texts(dst)
    assert "6083778353" not in out, "настоящий ИНН утек"
    assert "1063391630" in out, "артикул маскировать не надо"
    # подсказки одной книги не должны доставаться следующей
    assert masker.trusted_numbers == frozenset()


def test_requisites_next_to_label_cell_masked(tmp_path):
    """Счет, КПП и БИК без подписи в своей ячейке - подпись в соседней.

    Ячейка маскируется отдельно и подписи не видит: "Р/с" | "40817..." уходил
    открытым, хотя тот же счет в одной строке с подписью скрывался.
    """
    from pii_mask_enhanced.detection import presets
    from pii_mask_enhanced.engine.core import Masker

    pairs = [("Р/с", "40817810099910004312"), ("КПП", "770101001"), ("БИК", "044525225")]
    cells = {}
    for row, (label, number) in enumerate(pairs, 1):
        cells[f"A{row}"], cells[f"B{row}"] = label, number
    path = _grid_book(tmp_path / "req3.xlsx", cells)
    dst = tmp_path / "o3.xlsx"
    XLSX.mask(path, dst, Masker(types=presets.get("accounting").types, ner=False))
    out = XLSX.texts(dst)
    for _, number in pairs:
        assert number not in out, f"реквизит у подписи в соседней ячейке утек: {number}"
    assert {"Р/с", "КПП", "БИК"} <= set(out), "подписи маскировать не надо"


# --- утечки: текст книги вне ячеек ---

def _with_parts(path, parts: dict[str, str]):
    """Заменить или добавить части книги."""
    with zipfile.ZipFile(path) as z:
        old = {n: z.read(n) for n in z.namelist()}
    old.update({n: b.encode("utf-8") for n, b in parts.items()})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in old.items():
            z.writestr(n, b)
    return path


def _mask_part(tmp_path, parts, types, part):
    from pii_mask_enhanced.engine.core import Masker

    src = _with_parts(_book(tmp_path, shared=["Товар"]), parts)
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(types=types))
    return zipfile.ZipFile(dst).read(part).decode("utf-8")


def test_sheet_header_and_footer_are_masked(tmp_path):
    """Колонтитул печати - строка с кодами форматирования (&L, &R, &P) вокруг текста."""
    sheet = ('<?xml version="1.0"?><worksheet xmlns="x"><sheetData/><headerFooter>'
             "<oddHeader>&amp;LСоколова Анна Владимировна&amp;RСтр. &amp;P</oddHeader>"
             "<firstFooter>&amp;CООО «Ромашка»</firstFooter></headerFooter></worksheet>")
    body = _mask_part(tmp_path, {"xl/worksheets/sheet1.xml": sheet}, ("PERSON", "ORG"),
                      "xl/worksheets/sheet1.xml")
    assert "Соколова" not in body and "Ромашка" not in body
    assert "&amp;L" in body and "&amp;RСтр. &amp;P" in body and "&amp;C" in body


def test_threaded_comments_are_masked(tmp_path):
    """Цепочка примечаний (новые примечания Excel) хранит текст без узлов <t>."""
    tc = ('<?xml version="1.0"?><ThreadedComments xmlns="x">'
          '<threadedComment ref="A1" id="{1}" personId="{2}">'
          "<text>Ответственная: Соколова Анна Владимировна</text></threadedComment>"
          "</ThreadedComments>")
    body = _mask_part(tmp_path, {"xl/threadedComments/threadedComment1.xml": tc}, ("PERSON",),
                      "xl/threadedComments/threadedComment1.xml")
    assert "Соколова" not in body
    assert "Ответственная" in body


def test_comment_persons_are_cleared(tmp_path):
    persons = ('<?xml version="1.0"?><personList xmlns="x"><person displayName="Соколова Анна"'
               ' id="{2}" userId="sokolova@example.ru" providerId="None"/></personList>')
    body = _mask_part(tmp_path, {"xl/persons/person.xml": persons}, ("PERSON",),
                      "xl/persons/person.xml")
    assert "Соколова" not in body and "sokolova" not in body
    assert 'id="{2}"' in body


# --- числовые ячейки и подпись в шапке колонки ---

def _raw_sheet_book(path, shared: list[str], rows: dict[int, str]):
    """Книга с "сырыми" ячейками листа: числа, формулы с кэшем, t="str", пустые."""
    sst = ('<?xml version="1.0"?><sst>'
           + "".join(f"<si><t>{text}</t></si>" for text in shared) + "</sst>")
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             + "".join(f'<row r="{r}">{c}</row>' for r, c in sorted(rows.items()))
             + "</sheetData></worksheet>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def _mask_sheet(tmp_path, shared, rows) -> str:
    from pii_mask_enhanced.engine.core import Masker

    src = _raw_sheet_book(tmp_path / "in.xlsx", shared, rows)
    dst = tmp_path / "out.xlsx"
    XLSX.mask(src, dst, Masker(ner=False))
    return zipfile.ZipFile(dst).read("xl/worksheets/sheet1.xml").decode("utf-8")


def test_number_cell_with_pii_becomes_text_label(tmp_path):
    """ИНН и СНИЛС, сохраненные числом, раньше уходили открытыми. Стиль остается.
    ИНН узнается по контрольной сумме, слитный СНИЛС - по подписи в шапке колонки
    (без подписи 11 цифр - и телефон)."""
    sheet = _mask_sheet(tmp_path, ["СНИЛС"], {
        1: '<c r="B1" t="s"><v>0</v></c>',
        2: '<c r="A2" s="3"><v>7707083893</v></c><c r="B2" t="n"><v>11223344595</v></c>'})
    assert "7707083893" not in sheet and "11223344595" not in sheet
    assert '<c r="A2" s="3" t="inlineStr"><is><t xml:space="preserve">{{INN_1}}</t></is></c>' in sheet
    assert "{{SNILS_1}}" in sheet


def test_formula_cached_value_with_pii_is_masked(tmp_path):
    """В кэше формулы "=F3" - копия ИНН: формулу убираем, иначе кэш выдал бы исходник.
    Формула без ПД ("=SUM") остается формулой."""
    sheet = _mask_sheet(tmp_path, [], {
        1: '<c r="A1"><f>F3</f><v>7707083893</v></c><c r="B1"><f>SUM(C1:C9)</f><v>42</v></c>',
        2: '<c r="A2" t="str"><f>CONCATENATE(X1)</f><v>ivanov@mail.ru</v></c>'})
    assert "7707083893" not in sheet and "<f>F3</f>" not in sheet
    assert "<f>SUM(C1:C9)</f><v>42</v>" in sheet
    assert "ivanov@mail.ru" not in sheet and "user1@example.com" in sheet


def test_empty_cells_do_not_swallow_neighbours(tmp_path):
    """Пустая ячейка "<c r=... />" значения не имеет: соседнее число за ней не захватываем."""
    sheet = _mask_sheet(tmp_path, [], {
        1: '<c r="A1" s="1"/><c r="B1"><v>7707083893</v></c><c r="C1" s="2"/>'})
    assert '<c r="A1" s="1"/>' in sheet and '<c r="C1" s="2"/>' in sheet
    assert "{{INN_1}}" in sheet


def test_column_header_labels_every_row(tmp_path):
    """Подпись в шапке колонки, значения - во всех строках под ней, а не только в первой.
    Колонка без подписи ("Кол-во") остается числами."""
    shared = ["Табельный номер", "Оклад", "Кол-во", "Пол", "жен.", "муж."]
    rows = {1: '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
               '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c>'}
    for r, (tab, pay, qty, sex) in enumerate([("00123", "120000", "3", 4),
                                              ("124", "95000", "5", 5),
                                              ("125", "80000.5", "7", 4)], start=2):
        rows[r] = (f'<c r="A{r}"><v>{tab}</v></c><c r="B{r}"><v>{pay}</v></c>'
                   f'<c r="C{r}"><v>{qty}</v></c><c r="D{r}" t="s"><v>{sex}</v></c>')
    sheet = _mask_sheet(tmp_path, shared, rows)
    for leaked in ("00123", ">124<", ">125<", "120000", "95000", "80000.5"):
        assert leaked not in sheet, f"значение под шапкой утекло: {leaked}"
    for qty in ("<v>3</v>", "<v>5</v>", "<v>7</v>"):
        assert qty in sheet
    sst = zipfile.ZipFile(tmp_path / "out.xlsx").read("xl/sharedStrings.xml").decode("utf-8")
    assert "жен." not in sst and "муж." not in sst


def test_column_header_labelled_numbers(tmp_path):
    shared = ["Табельный номер", "Иванов"]
    path = _raw_sheet_book(tmp_path / "h.xlsx", shared, {
        1: '<c r="A1" t="s"><v>0</v></c>',
        2: '<c r="A2"><v>123</v></c>',
        3: '<c r="A3"><v>124</v></c>',
        40: '<c r="A40"><v>777</v></c>'})
    labelled = XLSX.labels(path)
    assert {"123", "124", "777"} <= set(labelled)
    assert labelled["777"][0] == "PERSON_ID"


def test_unmask_workbook_restores_text_and_numbers(tmp_path):
    """mask -> unmask возвращает книгу: текст на месте, число снова числовая ячейка."""
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «Ромашка»"], inline=["Петров Иван Сергеевич"],
                numbers=["771945678122", "7"])
    masked = tmp_path / "book.masked.xlsx"
    mapping = XLSX.mask(src, masked, Masker(types=("ORG", "PERSON", "INN")))
    assert "771945678122" not in XLSX.texts(masked)

    restored = tmp_path / "book.unmasked.xlsx"
    XLSX.unmask(masked, restored, mapping)
    assert XLSX.texts(restored) == XLSX.texts(src)
    sheet = zipfile.ZipFile(restored).read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="C1"><v>771945678122</v></c>' in sheet
    assert not (tmp_path / "book.unmasked.xlsx.tmp").exists()


def test_unmask_workbook_restores_number_from_shared_strings(tmp_path):
    """Книга, пересохраненная в Excel: метка числа уже в общей таблице строк, а не в ячейке."""
    src = _book(tmp_path, shared=["{{INN_1}}", "Итого"])
    mapping = {"version": 1, "labels": {"{{INN_1}}": {
        "type": "INN", "original": "7708123450", "key": "7708123450", "n": 1, "number": True}}}
    dst = tmp_path / "out.xlsx"
    XLSX.unmask(src, dst, mapping)
    sheet = zipfile.ZipFile(dst).read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="A1"><v>7708123450</v></c>' in sheet
    assert '<c r="A2" t="s"><v>1</v></c>' in sheet, "текстовая ячейка осталась ссылкой на строку"
    assert "{{INN_1}}" not in XLSX.texts(dst)


def test_unmask_workbook_keeps_text_label_as_text(tmp_path):
    """Метка в текстовой ячейке остается текстом, даже если оригинал - цифры."""
    src = _book(tmp_path, shared=["{{INN_1}}"])
    mapping = {"version": 1, "labels": {"{{INN_1}}": {
        "type": "INN", "original": "7708123450", "key": "7708123450", "n": 1}}}
    dst = tmp_path / "out.xlsx"
    XLSX.unmask(src, dst, mapping)
    assert XLSX.texts(dst) == ["7708123450"]
    assert "<v>7708123450</v>" not in zipfile.ZipFile(dst).read("xl/worksheets/sheet1.xml").decode()
