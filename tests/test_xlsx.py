"""Маскировка книги Excel: текст ячеек меняется, структура книги остается живой.

Фикстуры синтетические. Настоящие книги 1С кладут текст двумя разными способами
(общая таблица строк и инлайн прямо в листе), поэтому оба покрыты здесь.
"""
import zipfile

import pytest

from pii_mask_enhanced.formats import xlsx

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
    assert xlsx.cell_texts(src) == ["ООО «Ромашка»", "Контрагент", "Петров Иван"]


def test_numbers_are_not_text(tmp_path):
    """Числа и даты живут отдельным типом ячейки - маскировать их нечего."""
    src = _book(tmp_path, shared=["Доход"], numbers=["1000", "45678"])
    assert xlsx.cell_texts(src) == ["Доход"]


def test_rewrite_replaces_text_and_keeps_workbook_valid(tmp_path):
    src = _book(tmp_path, shared=["ООО «Ромашка»", "Контрагент"], inline=["Петров Иван"])
    dst = tmp_path / "out.xlsx"
    xlsx.rewrite(src, dst, ["{{ORG_1}}", "Контрагент", "{{PERSON_1}}"])
    assert xlsx.cell_texts(dst) == ["{{ORG_1}}", "Контрагент", "{{PERSON_1}}"]
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None
        # части книги не потеряны - иначе Excel откажется открывать
        assert "xl/workbook.xml" in z.namelist()
        assert "[Content_Types].xml" in z.namelist()


def test_rewrite_rejects_length_mismatch(tmp_path):
    """Рассинхрон списка значений - это сдвиг подстановки по всей книге."""
    src = _book(tmp_path, shared=["а", "б"])
    with pytest.raises(ValueError):
        xlsx.rewrite(src, tmp_path / "out.xlsx", ["только одно"])


def test_special_chars_survive_roundtrip(tmp_path):
    """Кавычки и амперсанд в названии - обычное дело у контрагентов."""
    src = _book(tmp_path, shared=['ООО "Р&Д" <тест>'])
    dst = tmp_path / "out.xlsx"
    xlsx.rewrite(src, dst, ['ЗАО "А&Б" <x>'])
    assert xlsx.cell_texts(dst) == ['ЗАО "А&Б" <x>']


def test_mask_workbook_masks_org_keeps_numbers(tmp_path):
    """Сквозной путь: книга на входе - книга на выходе, реестр общий на всю книгу."""
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «Ромашка»", "Содержание операции", "ООО «Ромашка»"],
                numbers=["1000"])
    dst = tmp_path / "out.xlsx"
    mapping = xlsx.mask_workbook(src, dst, Masker(types=("ORG", "PERSON")))
    out = xlsx.cell_texts(dst)
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
    xlsx.mask_workbook(src, dst, Masker(types=("ORG",)))
    out = xlsx.cell_texts(dst)
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
    assert xlsx.cell_texts(src) == ["one\ntwo", "x&y", "a&b"]


def test_escaped_reference_is_not_decoded_twice(tmp_path):
    """&amp;#10; означает литерал "&#10;", а не перевод строки."""
    src = _book(tmp_path, shared=["a&amp;#10;b"])
    assert xlsx.cell_texts(src) == ["a&#10;b"]


def test_roundtrip_preserves_reference_text(tmp_path):
    src = _book(tmp_path, shared=["one&#10;two"])
    dst = tmp_path / "out.xlsx"
    xlsx.rewrite(src, dst, xlsx.cell_texts(src))
    assert xlsx.cell_texts(dst) == ["one\ntwo"]


def test_carriage_return_survives(tmp_path):
    """Сырой \\r XML-парсер нормализует в \\n - его надо писать ссылкой."""
    src = _book(tmp_path, shared=["a"])
    dst = tmp_path / "out.xlsx"
    xlsx.rewrite(src, dst, ["строка\r\nвторая"])
    assert xlsx.cell_texts(dst) == ["строка\r\nвторая"]


# --- находки состязательного ревью ---

def test_refuses_to_write_over_source(tmp_path):
    """src == dst обнулял книгу до первого чтения: 22 КБ превращались в 22 байта."""
    src = _book(tmp_path, shared=["ООО «Ромашка»"])
    before = src.read_bytes()
    with pytest.raises(ValueError):
        xlsx.rewrite(src, src, ["{{ORG_1}}"])
    assert src.read_bytes() == before, "исходник должен остаться нетронутым"


def test_entity_swallowing_newline_does_not_break_book(tmp_path):
    """Распознаватель склеивает название через перенос - число строк меняется.

    Схема "склеить всё и разрезать обратно" на этом ломалась. Поячеечная
    маскировка к длине строк не привязана.
    """
    from pii_mask_enhanced.engine.core import Masker

    src = _book(tmp_path, shared=["ООО «СТРОЙМОНТАЖНАЛАДКА\nСТРОЙ»", "Итого"])
    dst = tmp_path / "out.xlsx"
    xlsx.mask_workbook(src, dst, Masker(types=("ORG",), ner=False))
    out = xlsx.cell_texts(dst)
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
    assert xlsx.cell_texts(path) == ["ООО «Ромашка»"]


def test_nonstandard_worksheet_name_is_scanned(tmp_path):
    """Имя части листа задаётся связями, а не обязано быть sheet1.xml."""
    path = tmp_path / "odd.xlsx"
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData><row><c t="inlineStr"><is><t>'
             'ООО «Ромашка»</t></is></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/worksheets/детализация.xml", sheet)
    assert xlsx.cell_texts(path) == ["ООО «Ромашка»"]


def test_unknown_text_part_refuses_instead_of_leaking(tmp_path):
    """Надпись на диаграмме мы обезличивать не умеем - значит не молчим.

    Тихо скопировать часть с текстом = выпустить ПД наружу без единой ошибки.
    """
    from pii_mask_enhanced.engine.core import Masker

    path = tmp_path / "draw.xlsx"
    drawing = ('<?xml version="1.0"?><xdr:wsDr xmlns:xdr="x" xmlns:a="y">'
               '<a:p><a:r><a:t>ООО «Ромашка»</a:t></a:r></a:p></xdr:wsDr>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst><si><t>Итого</t></si></sst>')
        z.writestr("xl/drawings/drawing1.xml", drawing)
    with pytest.raises(ValueError, match="drawing"):
        xlsx.mask_workbook(path, tmp_path / "o.xlsx", Masker(types=("ORG",), ner=False))


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
    xlsx.mask_workbook(path, dst, Masker(types=("ORG", "PERSON")))
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
    xlsx.mask_workbook(path, dst, Masker(types=("PERSON",)))
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
    xlsx.rewrite(path, dst, ["Итого"])          # значение то же самое
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
    xlsx.mask_workbook(src, dst, Masker(types=("PERSON", "ORG"),
                                        ner_org_needs_form=True,
                                        ner_person_needs_fio=True))
    out = xlsx.cell_texts(dst)
    assert "Метелина" not in " ".join(out), "фамилия контрагента утекла"
    assert "Аквабрис" in out[1], "марка товара не должна маскироваться"


def test_supported_names_scans_legal_form_cells(tmp_path):
    src = _book(tmp_path, shared=['ООО "Ромашка"', "ИП Метелина Лилия Вячеславовна",
                                  "Аквабрис"])
    names = xlsx.supported_names(src)
    assert "метелина" in names and "ромашка" in names
    assert "аквабрис" not in names


def test_number_next_to_label_is_trusted(tmp_path):
    """Подпись реквизита стоит в СОСЕДНЕЙ ячейке, а не в той же.

    В боевом отчете это A9='ИНН', B9='6083778353'. Маскировка идет по одной
    ячейке и соседей не видит, поэтому строгий режим пропускал настоящий ИНН,
    отсеивая заодно и артикулы. Смотреть надо на таблицу.
    """
    path = tmp_path / "req.xlsx"
    sst = ('<?xml version="1.0"?><sst><si><t>ИНН</t></si><si><t>6083778353</t></si>'
           '<si><t>1063391630</t></si></sst>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             '<row r="9"><c r="A9" t="s"><v>0</v></c><c r="B9" t="s"><v>1</v></c></row>'
             '<row r="20"><c r="C20" t="s"><v>2</v></c></row>'
             '</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    trusted = xlsx.labelled_numbers(path)
    assert "6083778353" in trusted, "ИНН рядом с подписью должен быть доверенным"
    assert "1063391630" not in trusted, "одинокий артикул подписи не имеет"


def test_strict_inn_masks_labelled_neighbour(tmp_path):
    from pii_mask_enhanced.engine.core import Masker

    path = tmp_path / "req2.xlsx"
    sst = ('<?xml version="1.0"?><sst><si><t>ИНН</t></si><si><t>6083778353</t></si>'
           '<si><t>1063391630</t></si></sst>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             '<row r="9"><c r="A9" t="s"><v>0</v></c><c r="B9" t="s"><v>1</v></c></row>'
             '<row r="20"><c r="C20" t="s"><v>2</v></c></row>'
             '</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    dst = tmp_path / "o.xlsx"
    masker = Masker(types=("INN",), inn_needs_label=True)
    xlsx.mask_workbook(path, dst, masker)
    out = xlsx.cell_texts(dst)
    assert "6083778353" not in out, "настоящий ИНН утек"
    assert "1063391630" in out, "артикул маскировать не надо"
    # подсказки одной книги не должны доставаться следующей
    assert masker.trusted_numbers == frozenset()


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
    xlsx.mask_workbook(src, dst, Masker(types=types))
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
