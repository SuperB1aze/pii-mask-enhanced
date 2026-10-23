"""Общий интерфейс форматов Office Open XML (.docx, .pptx, .xlsx): чтение, маскировка, восстановление."""
from __future__ import annotations

import re
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Iterable

from .office_xml import counterparty_words, mask_values, unknown_text_parts


class OfficeFormat(ABC):
    """Формат Office: что в нем читать, как писать обратно, как маскировать и восстанавливать."""
    where: str                                                   # "в документе" - для сообщений
    what: str                                                    # "документов Word" - для сообщений
    no_text: re.Pattern                                          # части, где текста не бывает
    parts: Callable[[zipfile.ZipFile], list[tuple[str, str]]]    # части в порядке обхода и их вид

    @abstractmethod
    def texts(self, path: str | Path) -> list[str]:
        """Текст, который мы умеем обезличивать, в устойчивом порядке."""

    @abstractmethod
    def labels(self, path: str | Path) -> dict[str, tuple[str, str]]:
        """Значения по подписи в таблице: значение -> (тип, ключ)."""

    @abstractmethod
    def rewrite(self, src: str | Path, dst: str | Path, values: list[str]) -> None:
        """Собрать копию файла с подставленными значениями в порядке texts."""

    @abstractmethod
    def mask(self, src: str | Path, dst: str | Path, masker, mapping: dict | None = None) -> dict:
        """Замаскировать файл в dst, вернуть маппинг."""

    @abstractmethod
    def unmask(self, src: str | Path, dst: str | Path, mapping: dict) -> None:
        """Вернуть оригиналы в файл того же формата."""

    def supported_names(self, path: str | Path) -> frozenset[str]:
        # слова из строк с правовой формой - для строгого режима распознавателя
        return counterparty_words(self.texts(path))

    @staticmethod
    def _check_target(src: Path, dst: Path) -> None:
        if dst.exists() and src.samefile(dst):
            # запись в тот же файл стерла бы исходник до чтения
            raise ValueError("нельзя писать поверх исходного файла - укажите другой файл")

    def _check_rewrite(self, src: Path, dst: Path, values: list[str]) -> None:
        self._check_target(src, dst)
        have = len(self.texts(src))
        if len(values) != have:
            raise ValueError(f"значений {len(values)}, а строк текста {self.where} {have} - "
                             "подстановка сдвинулась бы по всему тексту")

    def _check_known(self, z: zipfile.ZipFile, extra: Iterable[str] = ()) -> None:
        unknown = unknown_text_parts(z, {n for n, _ in self.parts(z)} | set(extra), self.no_text)
        if unknown:
            raise ValueError(f"{self.where.capitalize()} есть текст, с которым возникла проблема "
                             f"обезличивания: {unknown}, может произойти утечка ПД.")

    @staticmethod
    def _mask_texts(values: list[str], masker, mapping: dict | None,
                    labelled: dict[str, tuple[str, str]]):
        # маскировка строк файла с подсказками из него же; masker с подсказками - для остального файла
        hinted = masker.with_hints(counterparty_words(values), labelled)
        masked, mapping = mask_values(values, hinted, mapping)
        return masked, mapping, hinted
