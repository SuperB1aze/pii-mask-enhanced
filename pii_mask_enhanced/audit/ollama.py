"""Аудитор на локальной модели через Ollama. Нужен набор [audit] (httpx)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields
from pathlib import Path

from ..config import load_section
from .base import PROMPT, SCHEMA, chunks

log = logging.getLogger("pii_mask.auditor")


def _httpx():
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("для аудитора нужен httpx: pip install pii-mask-enhanced[audit]") from exc
    return httpx


@dataclass
class OllamaAuditor:
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:1.7b"
    timeout: float = 600.0
    # Держим модель загруженной между кусками одного документа, иначе она перезагружалась бы на каждом куске.
    keep_alive: str = "60s"
    chunk_chars: int = 2500     # под маленький контекст CPU-модели

    @classmethod
    def from_config(cls, path: str | Path | None = None, **overrides) -> OllamaAuditor:
        """Настройки из секции [audit] файла pii-mask.toml; overrides - поверх файла."""
        values = {**load_section("audit", path), **{k: v for k, v in overrides.items() if v is not None}}
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"неизвестные настройки аудитора: {', '.join(sorted(unknown))}")
        return cls(**values)

    def _client(self, timeout: float):
        # Ollama по определению локальная, `ALL_PROXY=socks5h://...` (типовой случай
        # на машине с прокси-каскадом) httpx применяет ко всем схемам и разворачивает
        # транспорт прямо при создании клиента. Без socksio это вызывает ошибку ImportError.
        return _httpx().Client(timeout=timeout, trust_env=False)

    def available(self) -> bool:
        _httpx()
        try:
            with self._client(3.0) as client:
                client.get(f"{self.url}/api/version").raise_for_status()
            return True
        except Exception:
            return False

    def find(self, masked_text: str) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        with self._client(self.timeout) as client:
            for chunk in chunks(masked_text, self.chunk_chars):
                try:
                    resp = client.post(
                        f"{self.url}/api/chat",
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": PROMPT + chunk}],
                            "format": SCHEMA,
                            "stream": False,
                            "think": False,  # для thinking-моделей (qwen3)
                            "keep_alive": self.keep_alive,
                            "options": {"temperature": 0},
                        },
                    )
                    resp.raise_for_status()
                    data = json.loads(resp.json()["message"]["content"])
                except Exception as exc:  # аудит - улучшение recall, не точка отказа
                    log.warning("auditor chunk failed: %s", exc)
                    continue
                found += [(str(item.get("text", "")), str(item.get("type", "OTHER")))
                          for item in data.get("entities", [])]
            self._unload(client)
        return found

    def _unload(self, client) -> None:
        # Выгрузить модель из памяти сразу, не дожидаясь keep_alive. Для гигиены памяти.
        try:
            client.post(
                f"{self.url}/api/generate",
                json={"model": self.model, "keep_alive": 0},
            ).raise_for_status()
        except Exception as exc:
            log.warning("Не удалось выгрузить модель: %s", exc)
