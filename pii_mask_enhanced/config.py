"""Файл настроек pii-mask.toml: где искать и как прочитать секцию.

Ищется по порядку: явно указанный путь, pii-mask.toml в текущем каталоге,
пользовательский конфиг (%APPDATA%\\pii-mask\\config.toml на Windows,
~/.config/pii-mask/config.toml на остальных системах).
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

CONFIG_NAME = "pii-mask.toml"


def user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "pii-mask" / "config.toml"


def find_config(path: str | Path | None = None) -> Path | None:
    """Путь к файлу настроек; None - файла нет. Явно указанный путь обязан существовать."""
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"файл настроек не найден: {path}")
        return path
    return next((p for p in (Path.cwd() / CONFIG_NAME, user_config_path()) if p.is_file()), None)


def load_section(name: str, path: str | Path | None = None) -> dict:
    """Секция [name] файла настроек; нет файла или секции - пустой словарь."""
    found = find_config(path)
    if found is None:
        return {}
    try:
        data = tomllib.loads(found.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{found}: ошибка в файле настроек - {exc}") from exc
    section = data.get(name, {})
    if not isinstance(section, dict):
        raise ValueError(f"{found}: [{name}] должна быть секцией")
    return section
