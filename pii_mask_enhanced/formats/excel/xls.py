"""Книга Excel 97-2003 (.xls): перевод в .xlsx внешним конвертером"""
from __future__ import annotations

from pathlib import Path

from ..common.legacy import MSO_FORCE_DISABLE_MACROS, ConvertError, LegacyFormat

_XL_FORMAT_XLSX = 51                  # xlOpenXMLWorkbook
_XL_FORMAT_XLS = 56                   # xlExcel8


def _via_excel(src: Path, outdir: Path, fmt: str) -> Path:
    import pythoncom
    import pywintypes
    import win32com.client

    dst = outdir / f"{src.stem}.{fmt}"
    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")  # свой экземпляр, не открытый пользователем
        try:
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.EnableEvents = False
            excel.AutomationSecurity = MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
            try:
                # пароль-заглушка: книга с паролем дает ошибку, а не окно ввода
                book = excel.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True, Password="#",
                                            IgnoreReadOnlyRecommended=True, AddToMru=False,
                                            Notify=False)
            except pywintypes.com_error as exc:
                raise ConvertError("Excel не открыл файл - он защищен паролем или поврежден") from exc
            try:
                book.RemovePersonalInformation = True
                book.CheckCompatibility = False
                book.SaveAs(str(dst), FileFormat=_XL_FORMAT_XLSX if fmt == "xlsx" else _XL_FORMAT_XLS)
            except pywintypes.com_error as exc:
                raise ConvertError(f"Excel не смог сохранить файл в .{fmt}") from exc
            finally:
                book.Close(SaveChanges=False)
        finally:
            excel.Quit()
    finally:
        pythoncom.CoUninitialize()
    return dst


XLS = LegacyFormat(".xls", ".xlsx", "xl/workbook.xml", "книгу Excel", "MS Excel", _via_excel)
