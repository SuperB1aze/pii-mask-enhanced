"""Презентация PowerPoint 97-2003 (.ppt): перевод в .pptx внешним конвертером"""
from __future__ import annotations

import re
from pathlib import Path

from ..common.legacy import MSO_FORCE_DISABLE_MACROS, ConvertError, LegacyFormat

_PP_SAVE_PPTX = 24                    # ppSaveAsOpenXMLPresentation
_PP_SAVE_PPT = 1                      # ppSaveAsPresentation
_PP_ALERTS_NONE = 1                   # ppAlertsNone

# Запись CurrentUserAtom в потоке Current User: по ее метке видно, зашифрована ли презентация
_CURRENT_USER_RE = re.compile(rb"\x00\x00\xf6\x0f.{4}\x14\x00\x00\x00(.{4})", re.S)
_ENCRYPTED_TOKEN = b"\xdf\xc4\xd1\xf3"                         # 0xF3D1C4DF, без пароля 0xE391C05F
# .pptx с паролем - тоже OLE2, внутри зашифрованный пакет
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")


def _locked(blob: bytes) -> bool:
    # PowerPoint на файле с паролем открывает окно ввода и ждет его вечно
    return _ENCRYPTED_PACKAGE in blob or any(
        m.group(1) == _ENCRYPTED_TOKEN for m in _CURRENT_USER_RE.finditer(blob))


def _via_powerpoint(src: Path, outdir: Path, fmt: str) -> Path:
    import pythoncom
    import pywintypes
    import win32com.client

    dst = outdir / f"{src.stem}.{fmt}"
    pythoncom.CoInitialize()
    try:
        # PowerPoint живет одним экземпляром
        app = win32com.client.DispatchEx("PowerPoint.Application")
        alerts, security = app.DisplayAlerts, app.AutomationSecurity
        try:
            app.DisplayAlerts = _PP_ALERTS_NONE
            app.AutomationSecurity = MSO_FORCE_DISABLE_MACROS  # макросы чужого файла не запускаем
            try:
                # файл с паролем сюда не доходит: его отсекает _locked
                pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
            except pywintypes.com_error as exc:
                raise ConvertError("PowerPoint не открыл файл - он поврежден") from exc
            try:
                pres.RemovePersonalInformation = True
                pres.SaveAs(str(dst), _PP_SAVE_PPTX if fmt == "pptx" else _PP_SAVE_PPT)
            except pywintypes.com_error as exc:
                raise ConvertError(f"PowerPoint не смог сохранить файл в .{fmt}") from exc
            finally:
                pres.Close()
        finally:
            app.DisplayAlerts, app.AutomationSecurity = alerts, security
            if app.Presentations.Count == 0:
                app.Quit()
    finally:
        pythoncom.CoUninitialize()
    return dst


PPT = LegacyFormat(".ppt", ".pptx", "ppt/presentation.xml", "презентацию PowerPoint",
                   "MS PowerPoint", _via_powerpoint, _locked)
