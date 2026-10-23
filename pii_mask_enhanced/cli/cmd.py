"""Обработчики подкоманд CLI: каждый принимает args и возвращает код выхода."""
from __future__ import annotations

import argparse
import functools
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple

from ..audit import OllamaAuditor
from ..config import load_section
from ..detection import presets
from ..detection.registry.entity_types import BY_NAME

from ..engine.core import Masker
from ..engine.settings import Options, build_masker, type_names

from .file_ops import FileOperations as ops

from ..formats import excel, powerpoint, word
from ..formats.common.legacy import ConvertError


class _Office(NamedTuple):
    """Формат Office Open XML: маскируется и восстанавливается в файл того же формата."""
    what: str                       # "книг" - для сообщений
    mask: Callable
    unmask: Callable


_OFFICE = {
    ".xlsx": _Office("книг", excel.mask_workbook, excel.unmask_workbook),
    ".docx": _Office("документов Word", word.mask_document, word.unmask_document),
    ".pptx": _Office("презентаций", powerpoint.mask_presentation, powerpoint.unmask_presentation),
}
# старый формат: работаем с его версией в новом
_LEGACY = {".doc": word.DOC, ".xls": excel.XLS, ".ppt": powerpoint.PPT}


class CliError(Exception):
    """Ошибка для пользователя: обработчик печатает ее в stderr и выходит с кодом 2."""


class CMD:
    @staticmethod
    def cmd_mask(args: argparse.Namespace) -> int:
        try:
            if args.file == "-" and not args.mapping:
                raise CliError("для stdin обязателен --mapping")

            src_path = None if args.file == "-" else Path(args.file)
            kind = src_path.suffix.lower() if src_path else ""
            if src_path is not None and kind in _LEGACY:
                return CMD.mask_legacy(args, src_path, kind)

            stem = src_path.with_suffix("") if src_path else None
            suffix = ".masked" + (".md" if kind in ("", ".pdf") else src_path.suffix)
            out = args.output or (f"{stem}{suffix}" if stem else None)
            mapping_path = args.mapping or f"{stem}.mapping.json"
            CMD._check_paths((out, mapping_path, "результат и реестр"),
                             (out, args.file, "результат и исходный файл"),
                             (mapping_path, args.file, "реестр и исходный файл"))

            # Текстовый вход читается один раз: stdin второй раз не прочитать, и
            # без кэша профиль съедал бы весь ввод, а маскировалась пустая строка.
            source = functools.cache(lambda: ops.read(args.file))

            # текст для профиля нужен и --preset auto, и --auto-profile: читаем один раз
            @functools.cache
            def probe() -> str | None:
                if kind in (*_OFFICE, ".pdf"):
                    return ops.probe_text(args.file, kind)
                try:
                    return source()
                except Exception:                     # noqa: BLE001
                    return None

            masker, org_names = CMD._build_masker(args, probe)
            mapping = ops.load_mapping(mapping_path)  # существующий mapping продолжаем

            if kind in _OFFICE:
                if args.audit:
                    raise CliError(f"--audit для {_OFFICE[kind].what} пока не поддержан: "
                                   "аудитор работает по тексту")
                if out is None or out == "-":
                    raise CliError("файл этого формата нельзя писать в stdout - укажи -o файл")
                try:
                    mapping = _OFFICE[kind].mask(args.file, out, masker, mapping)
                except ValueError as exc:   # в файле есть то, что не удается обезличить
                    raise CliError(str(exc)) from exc
            else:
                if kind == ".pdf":
                    # PDF читаем текстом и текстом же отдаем: собрать PDF обратно нельзя,
                    # замена другой длины ломает верстку строки (см. pii_mask_enhanced/formats/pdf/pdf.py).
                    from ..formats.pdf import PdfError, extract_text

                    try:
                        text = extract_text(args.file)
                    except PdfError as exc:
                        raise CliError(str(exc)) from exc
                else:
                    text = source()
                mask = masker.mask_with_audit if args.audit else masker.mask
                try:
                    masked, mapping = mask(text, mapping)
                except RuntimeError as exc:     # аудитор недоступен - fail-closed
                    raise CliError(str(exc)) from exc
                ops.write(out, masked)
        except CliError as exc:
            print(exc, file=sys.stderr)
            return 2

        ops.save_mapping(mapping_path, mapping)
        print(f"замаскировано сущностей: {len(mapping['labels'])}; mapping: {mapping_path}",
              file=sys.stderr)
        if org_names:
            CMD._report_org_dict(mapping, org_names)
        return 0

    @staticmethod
    def mask_legacy(args: argparse.Namespace, src_path: Path, kind: str) -> int:
        # .doc (.xls, .ppt) переводится во временный .docx (.xlsx, .pptx), маскируется в нем и
        # сохраняется обратно в старый формат (или в новый, если так задан -o)
        fmt = _LEGACY[kind]
        stem = src_path.with_suffix("")
        out = args.output or f"{stem}.masked{kind}"
        mapping_path = args.mapping or f"{stem}.mapping.json"
        CMD._check_paths((out, args.file, "результат и исходный файл"),
                         (mapping_path, args.file, "реестр и исходный файл"))
        to_old = Path(out).suffix.lower() == kind
        soffice = CMD._soffice(args)
        try:
            with fmt.as_new(src_path, soffice) as converted, \
                    tempfile.TemporaryDirectory(prefix="pii-legacy-") as tmp:
                if converted.suffix.lower() != fmt.new:
                    converted = Path(shutil.copyfile(converted, Path(tmp) / f"source{fmt.new}"))
                new_out = str(Path(tmp) / f"masked{fmt.new}") if to_old else out
                inner = argparse.Namespace(**{**vars(args), "file": str(converted),
                                              "output": new_out, "mapping": mapping_path})
                code = CMD.cmd_mask(inner)
                if code == 0 and to_old:
                    fmt.save_as_old(new_out, out, soffice)
                return code
        except ConvertError as exc:
            raise CliError(str(exc)) from exc

    @staticmethod
    def _settings(args: argparse.Namespace, section: str, env: dict[str, str]) -> dict:
        # Секция файла настроек, поверх нее - переменные окружения (env: ключ -> имя переменной).
        try:
            values = load_section(section, getattr(args, "config", None))
        except (FileNotFoundError, ValueError) as exc:
            raise CliError(str(exc)) from exc
        values.update({key: os.environ[var] for key, var in env.items() if os.environ.get(var)})
        return values

    @staticmethod
    def _soffice(args: argparse.Namespace) -> str | None:
        return CMD._settings(args, "convert", {"soffice": "PII_MASK_SOFFICE"}).get("soffice")

    @staticmethod
    def _auditor(args: argparse.Namespace) -> OllamaAuditor:
        values = CMD._settings(args, "audit", {"url": "PII_MASK_OLLAMA_URL",
                                               "model": "PII_MASK_AUDITOR_MODEL",
                                               "keep_alive": "PII_MASK_KEEP_ALIVE"})
        try:
            return OllamaAuditor(**values)
        except TypeError as exc:
            raise CliError(f"в секции [audit] неизвестная настройка: {exc}") from exc

    @staticmethod
    def _check_paths(*pairs: tuple[str | None, str | None, str]) -> None:
        # Пути считаются независимо, поэтому совпасть они могут молча: результат
        # успешно пишется, а следом затирается тем, что пишется вторым. Наружу это
        # выглядит как удачный прогон с кодом 0 и испорченным файлом.
        for a, b, what in pairs:
            if a and b and a != "-" and Path(a) == Path(b):
                raise CliError(f"{what} - один и тот же путь ({a}); один затрёт другой")

    @staticmethod
    def _build_masker(args: argparse.Namespace, probe) -> tuple[Masker, tuple[str, ...]]:
        # Настройки Masker из флагов и пресета. probe() - текст документа или None.
        org_names = ()
        if getattr(args, "org_dict", None):
            from ..detection.recognizers.recognizers import load_org_dict

            org_names = load_org_dict(args.org_dict)
        supported_names = ()
        if getattr(args, "supported_names", None):
            lines = Path(args.supported_names).read_text(encoding="utf-8").splitlines()
            supported_names = tuple(line.strip() for line in lines if line.strip())

        ner_types = getattr(args, "ner_types", None)
        opts = Options(
            preset=getattr(args, "preset", None),
            types=type_names(args.types.split(",") if args.types else None),
            ner=not args.no_ner,
            ner_types=type_names(ner_types.split(",") if ner_types else None),
            ner_org_needs_form=getattr(args, "ner_org_needs_form", False),
            ner_person_needs_fio=getattr(args, "ner_person_needs_fio", False),
            inn_needs_label=getattr(args, "inn_needs_label", False),
            auto_profile=getattr(args, "auto_profile", False),
            org_names=org_names,
            supported_names=supported_names,
        )
        auditor = CMD._auditor(args) if getattr(args, "audit", False) else None
        try:
            masker, notes = build_masker(opts, probe, auditor)
        except ValueError as exc:
            raise CliError(str(exc)) from exc
        for note in notes:
            print(note, file=sys.stderr)
        return masker, org_names

    @staticmethod
    def _report_org_dict(mapping: dict, org_names: tuple[str, ...]) -> None:
        # Сколько записей словаря реально сработало. Без этой строки запись, не давшая ни одного совпадения, ничем себя не выдает.
        used = {rec["key"] for rec in mapping["labels"].values() if rec["type"] == "ORG"}
        hit = [nm for nm in org_names if " ".join(nm.lower().split()) in used]
        print(f"словарь организаций: сработало {len(hit)} из {len(org_names)}", file=sys.stderr)
        if len(hit) < len(org_names):
            idle = [nm for nm in org_names if nm not in hit]
            shown = ", ".join(idle[:5]) + (f" и еще {len(idle) - 5}" if len(idle) > 5 else "")
            print(f"  не встретились в тексте: {shown}", file=sys.stderr)

    @staticmethod
    def cmd_unmask(args: argparse.Namespace) -> int:
        mapping = ops.load_mapping(args.mapping)
        if mapping is None:
            print(f"mapping не найден: {args.mapping}", file=sys.stderr)
            return 2
        src_path = Path(args.file)
        kind = src_path.suffix.lower() if args.file != "-" else ""
        if kind in _OFFICE:
            return CMD.unmask_office(args, src_path, kind, mapping)
        if kind in _LEGACY:
            return CMD.unmask_legacy(args, src_path, kind, mapping)
        restored = Masker(ner=False).unmask(ops.read(args.file), mapping)
        ops.write(args.output, restored)
        return 0

    @staticmethod
    def unmask_office(args: argparse.Namespace, src_path: Path, kind: str, mapping: dict) -> int:
        # Книга, документ Word и презентация восстанавливаются в файл того же формата
        stem = src_path.stem.removesuffix(".masked")
        out = args.output or str(src_path.with_name(f"{stem}.unmasked{src_path.suffix}"))
        if out == "-":
            print("файл этого формата нельзя писать в stdout - укажи -o файл", file=sys.stderr)
            return 2
        try:
            _OFFICE[kind].unmask(src_path, out, mapping)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"восстановлено: {out}", file=sys.stderr)
        return 0

    @staticmethod
    def unmask_legacy(args: argparse.Namespace, src_path: Path, kind: str, mapping: dict) -> int:
        # .doc (.xls, .ppt) -> временный .docx (.xlsx, .pptx) -> оригиналы -> снова старый формат
        fmt = _LEGACY[kind]
        stem = src_path.stem.removesuffix(".masked")
        out = args.output or str(src_path.with_name(f"{stem}.unmasked{kind}"))
        if out == "-":
            print("файл этого формата нельзя писать в stdout - укажи -o файл", file=sys.stderr)
            return 2
        if Path(out) == src_path:
            print(f"результат и исходный файл - один и тот же путь ({out})", file=sys.stderr)
            return 2
        try:
            soffice = CMD._soffice(args)
            with fmt.as_new(src_path, soffice) as converted, \
                    tempfile.TemporaryDirectory(prefix="pii-legacy-") as tmp:
                restored = Path(tmp) / f"restored{fmt.new}"
                _OFFICE[fmt.new].unmask(converted, restored, mapping)
                if Path(out).suffix.lower() == kind:
                    fmt.save_as_old(restored, out, soffice)
                else:
                    shutil.copyfile(restored, out)
        except (ConvertError, ValueError, CliError) as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"восстановлено: {out}", file=sys.stderr)
        return 0

    @staticmethod
    def cmd_presets(_args: argparse.Namespace) -> int:
        for name in presets.names():
            preset = presets.get(name)
            print(f"{name} - {preset.title}")
            for group, title in (("personal", "типы"), ("technical", "технические")):
                names = [t for t in preset.types if BY_NAME[t].group == group]
                if names:
                    print(f"  {title}: {','.join(names)}")
            print(f"  организация только с правовой формой: "
                  f"{'да' if preset.ner_org_needs_form else 'нет'}")
            print(f"  должность и специальность: {'оставить' if preset.keep_positions else 'скрыть'}")
            print(f"  остаток по счету и долг: {'оставить' if preset.keep_balances else 'скрыть'}")
        print(f"{presets.AUTO} - выбрать набор по профилю документа")
        return 0
