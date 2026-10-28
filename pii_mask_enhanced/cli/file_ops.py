"""Ввод-вывод CLI: файлы и stdin/stdout, реестр замен."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


class FileOperations:
    @staticmethod
    def read(src: str) -> str:
        if src == "-":
            return sys.stdin.read()
        return Path(src).read_text(encoding="utf-8")

    @staticmethod
    def write(dst: str | None, content: str) -> None:
        if dst is None or dst == "-":
            sys.stdout.write(content)
            return
        Path(dst).write_text(content, encoding="utf-8")

    @staticmethod
    def load_mapping(path: str | None) -> dict | None:
        if path and Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
        return None

    @staticmethod
    def save_mapping(path: str, mapping: dict) -> None:
        p = Path(path)
        p.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
        os.chmod(p, 0o600)
        # mapping может содержать персональные данные, поэтому на Unix/Linux системах реализована выдача
        # права 600 (только владелец может читать и писать файл)
