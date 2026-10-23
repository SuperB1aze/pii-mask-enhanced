"""Собрать эталонные файлы Office для test_golden_office.py. Нужны Windows, MS Office и pywin32.

    python tests/golden/office/build.py

Файлы делает настоящий Office: только в них есть части, которых нет в самодельных
фикстурах, - миниатюра слайда, путь сохранения, автор сводной таблицы. Автор и путь
сохранения машины, где идет сборка, заменяются на вымышленные - в репозиторий не
должны попасть ни имя пользователя, ни его каталоги.
"""
import io
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pythoncom
import win32com.client

HERE = Path(__file__).parent
FAKE_AUTHOR = "Лебедева Ирина"
FAKE_DIR = "C:\\Users\\lebedeva\\Documents\\"
ROWS = [("ФИО", "Почта", "Оклад"),
        ("Соколова Анна Владимировна", "sokolova@example.ru", 120000),
        ("Воронцов Андрей Игоревич", "vorontsov@example.ru", 95000)]


def fill(ws):
    for r, row in enumerate(ROWS, 1):
        for c, v in enumerate(row, 1):
            ws.Cells(r, c).Value = v


def chart_data(chart):
    chart.ChartData.Activate()
    wb = chart.ChartData.Workbook
    ws = wb.Worksheets(1)
    ws.Range("A1:D5").ClearContents()
    fill(ws)
    chart.SetSourceData(f"='{ws.Name}'!$A$1:$A$3,'{ws.Name}'!$C$1:$C$3")
    wb.Close()


def build_word(path: Path):
    app = win32com.client.DispatchEx("Word.Application")
    app.Visible = False
    try:
        doc = app.Documents.Add()
        doc.Content.Text = "Отчет для руководства. Ответственный: Воронцов Андрей Игоревич."
        shp = doc.InlineShapes.AddChart2(-1, 51)
        chart_data(shp.Chart)
        shp.Chart.HasTitle = True
        shp.Chart.ChartTitle.Text = "Оклады: Соколова Анна и ООО «Ромашка»"
        shp.AlternativeText = "Диаграмма для sokolova@example.ru"
        art = doc.Shapes.AddSmartArt(app.SmartArtLayouts(1), 50, 300, 300, 150)
        art.SmartArt.AllNodes(1).TextFrame2.TextRange.Text = "Директор Соколова Анна Владимировна"
        art.SmartArt.AllNodes(2).TextFrame2.TextRange.Text = "Заместитель Воронцов Андрей Игоревич"
        doc.SaveAs2(str(path), FileFormat=16)
        doc.Close(False)
    finally:
        app.Quit()


def build_excel(path: Path):
    app = win32com.client.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    try:
        wb = app.Workbooks.Add()
        ws = wb.Worksheets(1)
        ws.Name = "Соколова А.В."
        fill(ws)
        ws2 = wb.Worksheets.Add(After=ws)
        ws2.Name = "Итоги"
        ws2.Range("A1").Formula = "='Соколова А.В.'!C2"
        ws.Shapes.AddChart2(-1, 51, 300, 10, 300, 200).Chart.SetSourceData(
            app.Union(ws.Range("A1:A3"), ws.Range("C1:C3")))
        box = ws.Shapes.AddTextbox(1, 10, 120, 250, 40)
        box.TextFrame2.TextRange.Text = "Подготовила Соколова Анна, ООО «Ромашка»"
        box.AlternativeText = "Пишите на sokolova@example.ru"
        pt = wb.PivotCaches().Create(1, ws.Range("A1:C3")).CreatePivotTable(ws2.Range("C3"), "Сводная")
        pt.PivotFields("ФИО").Orientation = 1
        pt.AddDataField(pt.PivotFields("Оклад"))
        wb.SaveAs(str(path), FileFormat=51)
        wb.Close(False)
    finally:
        app.Quit()


def build_powerpoint(path: Path):
    app = win32com.client.DispatchEx("PowerPoint.Application")
    try:
        pres = app.Presentations.Add(WithWindow=True)    # диаграмму PowerPoint без окна не создает
        app.WindowState = 2
        slide = pres.Slides.Add(1, 12)
        shp = slide.Shapes.AddChart2(-1, 51, 20, 20, 400, 250)
        chart_data(shp.Chart)
        shp.Chart.HasTitle = True
        shp.Chart.ChartTitle.Text = "Оклады: ООО «Ромашка»"
        art = slide.Shapes.AddSmartArt(app.SmartArtLayouts(1), 450, 20, 250, 200)
        art.SmartArt.AllNodes(1).TextFrame2.TextRange.Text = "Директор Соколова Анна Владимировна"
        art.AlternativeText = "Схема, vorontsov@example.ru"
        pres.SaveAs(str(path), 24)
        pres.Close()
    finally:
        if app.Presentations.Count == 0:
            app.Quit()


def _authors(blob: bytes) -> set[bytes]:
    # кто создал и сохранил файл - из docProps/core.xml
    return {m.group(1) for m in re.finditer(rb"<(?:dc:creator|cp:lastModifiedBy)>([^<]+)<", blob)}


def _scrub(blob: bytes, swaps: list[tuple[bytes, bytes]]) -> bytes:
    """Заменить автора и путь во всех частях архива, в том числе во вложенных."""
    if blob[:4] != b"PK\x03\x04":
        for old, new in swaps:
            blob = blob.replace(old, new)
        return blob
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, _scrub(zin.read(info), swaps))
    return out.getvalue()


def main():
    pythoncom.CoInitialize()
    with tempfile.TemporaryDirectory(prefix="pii-golden-") as tmp:
        work = Path(tmp).resolve()
        # Excel последним: данные диаграмм Word и PowerPoint редактируются через Excel, и
        # закрывающийся экземпляр Excel обрывает их вызовы ("Сервер RPC недоступен")
        for name, build in [("report.docx", build_word), ("deck.pptx", build_powerpoint),
                            ("staff.xlsx", build_excel)]:
            path = work / name
            build(path)
            time.sleep(3)
            blob = path.read_bytes()
            with zipfile.ZipFile(path) as z:
                authors = _authors(z.read("docProps/core.xml"))
            swaps = [(a, FAKE_AUTHOR.encode()) for a in authors]
            swaps.append((str(work).encode() + b"\\", FAKE_DIR.encode()))
            (HERE / name).write_bytes(_scrub(blob, swaps))
            print(name, "авторы заменены:", [a.decode() for a in authors])


if __name__ == "__main__":
    sys.exit(main())
