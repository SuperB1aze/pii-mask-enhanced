"""Маскировка книги Excel (.xlsx) без внешних зависимостей.

Книга - это zip с XML внутри, и текст в ней живет не только в ячейках:

- общая таблица строк `xl/sharedStrings.xml` (`<si>`) - так пишет 1С и почти все;
- инлайн прямо в листе (`<is>`) - реже, но встречается;
- комментарии к ячейкам (`xl/comments*.xml`) - текст и имя автора;
- свойства файла (`docProps/core.xml`) - кто сохранил книгу.

Обходятся все четыре. Числа, даты и формулы не трогаются: они лежат отдельными
типами ячейки, ПД в них не бывает, а порча числа тихо ломает свод.

**Незнакомая часть с текстом - отказ, а не пропуск.** Надпись на диаграмме или
текстовое поле мы обезличивать не умеем; молча скопировать такую часть значит
выпустить ПД наружу без единой ошибки - ровно тот тихий отказ, ради которого
инструмент и существует. Поэтому `mask_workbook` останавливается и называет
часть. Чего инструмент по-прежнему НЕ трогает - названия листов: они лежат
атрибутом в `xl/workbook.xml`, и на них ссылаются формулы, так что переименование
книгу ломает.

Правки точечные, по текстовым узлам, и только там, где значение изменилось:
остальные части и неизменившиеся ячейки копируются байт в байт. Пересборка
книги через разбор и повторную сериализацию всего XML переставляет атрибуты и
объявления пространств имен, после чего Excel может отказаться открывать файл.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# Ссылки на символы: числовые (`&#10;` - так Excel хранит перевод строки внутри
# ячейки) и пять именованных, которые определяет сам XML.
_REF_RE = re.compile(r"&(?:#x([0-9A-Fa-f]+)|#(\d+)|(amp|lt|gt|quot|apos));")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _unescape(text: str) -> str:
    """Разобрать ссылки на символы за ОДИН проход.

    Последовательная замена (сперва `&amp;`, потом числовые) разбирает результат
    собственной работы: `&amp;#10;` - это литерал `&#10;`, а после двух проходов
    он превратился бы в перевод строки. Один проход слева направо - ровно то,
    что делает настоящий XML-парсер.
    """
    def one(m: re.Match) -> str:
        if m.group(1):
            return chr(int(m.group(1), 16))
        if m.group(2):
            return chr(int(m.group(2)))
        return _NAMED[m.group(3)]

    return _REF_RE.sub(one, text)


def _escape(text: str) -> str:
    """Экранировать текст ячейки.

    Возврат каретки пишется ссылкой: сырой `\\r` XML-парсер нормализует в `\\n`
    еще до нас, и символ потеряется молча.
    """
    return escape(text).replace("\r", "&#13;")


def _tag(name: str) -> bytes:
    """Тег с необязательным префиксом пространства имен: `<si>` и `<x:si>`."""
    return rf"<(?:\w+:)?{name}(?:\s[^>]*)?>(.*?)</(?:\w+:)?{name}>".encode()


# Контейнеры набора ранов <t>: ячейка в общей таблице, инлайновая ячейка листа,
# тело комментария. Имя автора комментария - отдельный узел, не <t>.
_ITEM_RE = {k: re.compile(_tag(k), re.S) for k in ("si", "is", "text", "author")}
_T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?>(.*?)</(?:\w+:)?t>|<(?:\w+:)?t(?:\s[^>]*)?/>", re.S)
# Любой текстовый узел - чтобы заметить текст в частях, которые мы не разбираем.
_ANY_T_RE = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?>([^<]+)</(?:\w+:)?t>", re.S)

# Части, где мы умеем читать текст, в порядке обхода. Имя части листа задается
# связями и не обязано быть sheet1.xml, поэтому берем любое.
_PART_KINDS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^xl/sharedStrings\.xml$"), "si"),
    (re.compile(r"^xl/worksheets/[^/]+\.xml$"), "is"),
    (re.compile(r"^xl/comments\d*\.xml$"), "author"),
    (re.compile(r"^xl/comments\d*\.xml$"), "text"),
)

# Части без пользовательского текста: разметка, оформление, связи.
_NO_TEXT = re.compile(
    r"^(\[Content_Types\]\.xml|_rels/|xl/_rels/|xl/styles\.xml|xl/theme/|"
    r"xl/workbook\.xml|xl/calcChain\.xml|xl/sharedStrings\.xml|"
    r"xl/worksheets/|xl/comments\d*\.xml|docProps/)"
)

# Имя того, кто сохранил книгу.
_AUTHOR_FIELDS = ("dc:creator", "cp:lastModifiedBy")


def _sort_key(name: str) -> tuple:
    """sheet2 раньше sheet10; прочие имена - по алфавиту, но устойчиво."""
    m = re.search(r"(\d+)\.xml$", name)
    return (0, int(m.group(1)), "") if m else (1, 0, name)


def _parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Части с текстом и вид контейнера, в устойчивом порядке обхода."""
    out: list[tuple[str, str]] = []
    for rx, kind in _PART_KINDS:
        names = sorted((n for n in z.namelist() if rx.match(n)), key=_sort_key)
        out.extend((n, kind) for n in names)
    return out


def _unknown_text_parts(z: zipfile.ZipFile) -> list[str]:
    """Части с текстом, которые мы не разбираем: диаграммы, надписи, чужое."""
    known = {n for n, _ in _parts(z)}
    bad = []
    for n in z.namelist():
        if n in known or _NO_TEXT.match(n) or not n.endswith(".xml"):
            continue
        if any(m.group(1).strip() for m in _ANY_T_RE.finditer(z.read(n))):
            bad.append(n)
    return sorted(bad)


def _item_value(body: bytes, kind: str) -> str:
    if kind == "author":
        return _unescape(body.decode("utf-8"))
    runs = [m.group(1) or b"" for m in _T_RE.finditer(body)]
    return _unescape(b"".join(runs).decode("utf-8"))


def cell_texts(path: str | Path) -> list[str]:
    """Весь текст книги, который мы умеем обезличивать, в устойчивом порядке."""
    values: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name, kind in _parts(z):
            for item in _ITEM_RE[kind].finditer(z.read(name)):
                values.append(_item_value(item.group(1), kind))
    return values


def _rewrite_part(blob: bytes, kind: str, values: list[str], cursor: int) -> tuple[bytes, int]:
    def one(match: re.Match) -> bytes:
        nonlocal cursor
        body = match.group(1)
        new, cursor = values[cursor], cursor + 1
        whole = match.group(0)
        head = whole[:match.start(1) - match.start(0)]
        tail = whole[match.end(1) - match.start(0):]

        if _item_value(body, kind) == new:
            # Значение не изменилось - не трогаем: схлопывание ранов потеряло бы
            # посимвольное оформление там, где мы ничего не маскировали.
            return whole

        payload = _escape(new).encode("utf-8")
        if kind == "author":
            return head + payload + tail

        first = True

        def run(_t: re.Match) -> bytes:
            nonlocal first
            if not first:
                return b"<t/>"      # рич-текст схлопываем в первый ран
            first = False
            return b'<t xml:space="preserve">' + payload + b"</t>"

        return head + _T_RE.sub(run, body) + tail

    return _ITEM_RE[kind].sub(one, blob), cursor


def _strip_authors(blob: bytes) -> bytes:
    """Вычистить имя того, кто сохранил книгу, из свойств файла."""
    for field in _AUTHOR_FIELDS:
        blob = re.sub(rf"<{field}>[^<]*</{field}>".encode(),
                      f"<{field}></{field}>".encode(), blob)
    return blob


def rewrite(src: str | Path, dst: str | Path, values: list[str]) -> None:
    """Собрать копию книги с подставленными значениями.

    `values` - ровно то, что вернул `cell_texts` для этой же книги, в том же
    порядке. Рассинхрон длины - это сдвиг подстановки по всей книге, поэтому он
    ошибка, а не повод обрезать по короткому списку.
    """
    src, dst = Path(src), Path(dst)
    if dst.exists() and src.samefile(dst):
        # Запись открывает тот же путь на "w" и обнуляет его ДО первого чтения:
        # книга уничтожалась целиком, а падало уже на усечённом архиве.
        raise ValueError("нельзя писать поверх исходной книги - укажи другой файл")
    have = cell_texts(src)
    if len(values) != len(have):
        raise ValueError(
            f"значений {len(values)}, а текстовых узлов в книге {len(have)} - "
            "подстановка сдвинулась бы по всей книге")

    cursor = 0
    with zipfile.ZipFile(src) as zin:
        # Курсор обязан идти в том же порядке, в котором значения отдал
        # cell_texts, а порядок частей в архиве свой - поэтому правим по _parts,
        # накапливая результат, и только потом пишем архив.
        done: dict[str, bytes] = {}
        for name, kind in _parts(zin):
            blob = done.get(name) or zin.read(name)
            blob, cursor = _rewrite_part(blob, kind, values, cursor)
            done[name] = blob
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                blob = done.get(info.filename) or zin.read(info.filename)
                if info.filename == "docProps/core.xml":
                    blob = _strip_authors(blob)
                zout.writestr(info, blob)   # прочие части - как были


# Правовые формы: по ним книга сама объявляет, кто в ней контрагент.
_LEGAL_FORM = re.compile(
    r"\b(ООО|ЗАО|ОАО|ПАО|НАО|АО|ИП|АНО|НКО|ФГУП|ГУП|МУП|ФГБУ)\b", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[^\w\-]+")


def supported_names(src: str | Path) -> tuple[str, ...]:
    """Слова из ячеек с правовой формой - имена, которые книга назвала своими.

    Нужны строгому режиму распознавателя: фамилию "Метелина" словарь не знает
    ровно так же, как марку "Аквабрис", и отличает их только документ. Ячейка
    "ИП Метелина Лилия Вячеславовна" объявляет Метелину контрагентом, и дальше
    фамилия маскируется даже там, где стоит одна. Рядом с маркой правовой формы
    нет нигде в книге, поэтому в список она не попадает.
    """
    names: set[str] = set()
    for value in cell_texts(src):
        if not _LEGAL_FORM.search(value):
            continue
        for word in _WORD_SPLIT.split(value):
            if len(word) >= 3 and not word.isdigit() and not _LEGAL_FORM.fullmatch(word):
                names.add(word.lower())
    return tuple(sorted(names))


# Ячейка листа с координатой. Значение либо ссылка в общую таблицу (t="s"),
# либо инлайн (t="inlineStr"), либо число - последнее нас не интересует.
_CELL_RE = re.compile(
    rb'<c\s+r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_V_RE = re.compile(rb"<(?:\w+:)?v>(.*?)</(?:\w+:)?v>", re.S)

# Подписи реквизитов: слово рядом с числом делает число реквизитом.
_REQ_LABEL = re.compile(r"^\s*(ИНН|КПП|ОГРН|ОГРНИП|БИК|СНИЛС|ОКПО|ОКТМО)\s*:?\s*$",
                        re.IGNORECASE)
_DIGITS_ONLY = re.compile(r"^\s*\d{5,20}\s*$")


def _col_num(letters: bytes) -> int:
    n = 0
    for ch in letters.decode():
        n = n * 26 + (ord(ch) - 64)
    return n


def _sheet_grid(z: zipfile.ZipFile, name: str, shared: list[str]) -> dict[tuple[int, int], str]:
    """Текстовые значения листа по координатам (строка, колонка)."""
    grid: dict[tuple[int, int], str] = {}
    for m in _CELL_RE.finditer(z.read(name)):
        col, row, attrs, body = _col_num(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        if body is None:
            continue
        if b't="s"' in attrs:
            v = _V_RE.search(body)
            if v is not None:
                idx = int(v.group(1))
                if 0 <= idx < len(shared):
                    grid[(row, col)] = shared[idx]
        elif b't="inlineStr"' in attrs:
            grid[(row, col)] = _item_value(body, "is")
    return grid


def labelled_numbers(src: str | Path) -> frozenset[str]:
    """Числа, у которых в соседней ячейке стоит подпись реквизита.

    Подпись в бухгалтерских формах живет отдельной ячейкой слева или сверху
    ("A9=ИНН", "B9=6083778353"), а маскировка идет по одной ячейке и соседей не
    видит. Без этой сверки строгий режим отсекал артикулы вместе с настоящими
    реквизитами - одинаковые на вид десятизначные числа.
    """
    out: set[str] = set()
    with zipfile.ZipFile(src) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            blob = z.read("xl/sharedStrings.xml")
            shared = [_item_value(i.group(1), "si") for i in _ITEM_RE["si"].finditer(blob)]
        for name in (n for n in z.namelist() if re.match(r"^xl/worksheets/[^/]+\.xml$", n)):
            grid = _sheet_grid(z, name, shared)
            for (row, col), value in grid.items():
                if not _DIGITS_ONLY.match(value):
                    continue
                left = grid.get((row, col - 1), "")
                above = grid.get((row - 1, col), "")
                if _REQ_LABEL.match(left) or _REQ_LABEL.match(above):
                    out.add(value.strip())
    return frozenset(out)


def mask_workbook(src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
    """Замаскировать книгу целиком: на входе .xlsx, на выходе .xlsx и реестр.

    Значения маскируются по одному, а не одной склейкой: распознаватель умеет
    поглощать перенос строки внутри названия, из-за чего число строк меняется, и
    любая схема "склеить и разрезать обратно" разъезжается по ячейкам. Реестр
    при этом общий на всю книгу - одна сущность получает одну метку везде.
    """
    with zipfile.ZipFile(src) as z:
        unknown = _unknown_text_parts(z)
    if unknown:
        raise ValueError(
            "в книге есть текст, который я не умею обезличивать: "
            + ", ".join(unknown)
            + " - скопировать её как есть значит выпустить ПД наружу молча")

    # Строгому режиму нужны опорные имена, а видит книгу целиком только эта
    # функция: маскировщик работает по одной ячейке и соседних не знает.
    if getattr(masker, "ner_person_needs_fio", False) and not masker.supported_names:
        masker.supported_names = frozenset(supported_names(src))
    # То же самое для реквизитов: подпись стоит в соседней ячейке, и увидеть её
    # может только тот, кто смотрит на таблицу целиком.
    if getattr(masker, "inn_needs_label", False) and not masker.trusted_numbers:
        masker.trusted_numbers = labelled_numbers(src)

    masked = []
    for value in cell_texts(src):
        if not value.strip():
            masked.append(value)
            continue
        out, mapping = masker.mask(value, mapping)
        masked.append(out)
    rewrite(src, dst, masked)
    return mapping
