"""Книга Excel 97-2003 (.xls): перевод в .xlsx внешним конвертером"""
from __future__ import annotations

from pathlib import Path

from ..common.legacy import MSO_FORCE_DISABLE_MACROS, LegacyFormat, com_failure, office_app

_XL_FORMAT_XLSX = 51                  # xlOpenXMLWorkbook
_XL_FORMAT_XLS = 56                   # xlExcel8


def _via_excel(src: Path, outdir: Path, fmt: str) -> Path:
    dst = outdir / f"{src.stem}.{fmt}"
    with office_app("Excel.Application", lambda app: app.Quit()) as excel:
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.EnableEvents = False
        excel.AutomationSecurity = MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
        with com_failure("Excel не открыл файл - он защищен паролем или поврежден"):
            # пароль-заглушка: книга с паролем дает ошибку, а не окно ввода
            book = excel.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True, Password="#",
                                        IgnoreReadOnlyRecommended=True, AddToMru=False,
                                        Notify=False)
        try:
            with com_failure(f"Excel не смог сохранить файл в .{fmt}"):
                book.RemovePersonalInformation = True
                book.CheckCompatibility = False
                book.SaveAs(str(dst), FileFormat=_XL_FORMAT_XLSX if fmt == "xlsx" else _XL_FORMAT_XLS)
        finally:
            book.Close(SaveChanges=False)
    return dst


XLS = LegacyFormat(".xls", ".xlsx", "xl/workbook.xml", "книгу Excel", "MS Excel", _via_excel)
