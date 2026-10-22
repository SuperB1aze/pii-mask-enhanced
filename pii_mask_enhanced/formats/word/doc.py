"""Документ Word 97-2003 (.doc): перевод в .docx внешним конвертером"""
from __future__ import annotations

from pathlib import Path

from ..common.legacy import MSO_FORCE_DISABLE_MACROS, ConvertError, LegacyFormat

_WD_FORMAT_DOCX = 16                  # wdFormatDocumentDefault
_WD_FORMAT_DOC = 0                    # wdFormatDocument97


def _via_word(src: Path, outdir: Path, fmt: str) -> Path:
    import pythoncom
    import pywintypes
    import win32com.client

    dst = outdir / f"{src.stem}.{fmt}"
    pythoncom.CoInitialize()        # без этого COM не работает вне главного потока
    try:
        word = win32com.client.DispatchEx("Word.Application")  # свой экземпляр, не открытый пользователем
        try:
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
            try:
                doc = word.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                          AddToRecentFiles=False, PasswordDocument="#",
                                          Visible=False, NoEncodingDialog=True)
            except pywintypes.com_error as exc:
                raise ConvertError("Word не открыл файл - он защищен паролем или поврежден") from exc
            try:
                doc.RemovePersonalInformation = True
                doc.SaveAs2(str(dst), FileFormat=_WD_FORMAT_DOCX if fmt == "docx" else _WD_FORMAT_DOC)
            except pywintypes.com_error as exc:
                raise ConvertError(f"Word не смог сохранить файл в .{fmt}") from exc
            finally:
                doc.Close(SaveChanges=0)
        finally:
            word.Quit(SaveChanges=0)
    finally:
        pythoncom.CoUninitialize()
    return dst


DOC = LegacyFormat(".doc", ".docx", "word/document.xml", "документ Word", "MS Word", _via_word)
