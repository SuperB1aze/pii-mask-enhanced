"""Документ Word 97-2003 (.doc): перевод в .docx внешним конвертером"""
from __future__ import annotations

from pathlib import Path

from ..common.legacy import MSO_FORCE_DISABLE_MACROS, LegacyFormat, com_failure, office_app

_WD_FORMAT_DOCX = 16                  # wdFormatDocumentDefault
_WD_FORMAT_DOC = 0                    # wdFormatDocument97


def _via_word(src: Path, outdir: Path, fmt: str) -> Path:
    dst = outdir / f"{src.stem}.{fmt}"
    with office_app("Word.Application", lambda app: app.Quit(SaveChanges=0)) as word:
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
        with com_failure("Word не открыл файл - он защищен паролем или поврежден"):
            doc = word.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                      AddToRecentFiles=False, PasswordDocument="#",
                                      Visible=False, NoEncodingDialog=True)
        try:
            with com_failure(f"Word не смог сохранить файл в .{fmt}"):
                doc.RemovePersonalInformation = True
                doc.SaveAs2(str(dst), FileFormat=_WD_FORMAT_DOCX if fmt == "docx" else _WD_FORMAT_DOC)
        finally:
            doc.Close(SaveChanges=0)
    return dst


DOC = LegacyFormat(".doc", ".docx", "word/document.xml", "документ Word", "MS Word", _via_word)
