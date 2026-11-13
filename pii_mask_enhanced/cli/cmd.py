"""Обработчики подкоманд CLI: каждый принимает args и возвращает код выхода."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .. import api
from ..audit import OllamaAuditor
from ..config import load_section
from ..detection import presets
from ..detection.registry.entity_types import BY_NAME
from ..engine.settings import Options, type_names

from .file_ops import FileOperations as ops

_FILES = (*api.OFFICE, *api.LEGACY)


class CliError(Exception):
    """Ошибка для пользователя: обработчик печатает ее в stderr и выходит с кодом 2."""


def _note(text: str) -> None:
    print(text, file=sys.stderr)


class CMD:
    @staticmethod
    def cmd_mask(args: argparse.Namespace) -> int:
        try:
            if args.file == "-" and not args.mapping:
                raise CliError("для stdin обязателен --mapping")

            src_path = None if args.file == "-" else Path(args.file)
            kind = src_path.suffix.lower() if src_path else ""
            stem = src_path.with_suffix("") if src_path else None
            if kind in api.LEGACY:
                suffix = ".masked" + kind
            else:
                suffix = ".masked" + (src_path.suffix if src_path and kind not in ("", ".pdf") else ".md")
            out = args.output or (f"{stem}{suffix}" if stem else None)
            if args.mapping:
                mapping_path = args.mapping
            elif out and out != "-":
                output_path = Path(out)
                output_stem = output_path.stem.removesuffix(".masked")
                mapping_path = str(output_path.with_name(f"{output_stem}.mapping.json"))
            else:
                mapping_path = f"{stem}.mapping.json"
            CMD._check_paths((out, mapping_path, "результат и реестр"),
                             (out, args.file, "результат и исходный файл"),
                             (mapping_path, args.file, "реестр и исходный файл"))

            opts = CMD._options(args)
            auditor = CMD._auditor(args) if getattr(args, "audit", False) else None
            mapping = ops.load_mapping(mapping_path)  # существующий mapping продолжаем

            if kind in _FILES:
                if out is None or out == "-":
                    raise CliError("файл этого формата нельзя писать в stdout - укажи -o файл")
                soffice = CMD._soffice(args) if kind in api.LEGACY else None
                mapping = api.mask_file(args.file, out, opts, mapping,
                                        soffice=soffice, auditor=auditor, report=_note)
            else:
                text = api.read_text(args.file) if kind == ".pdf" else ops.read(args.file)
                masked, mapping = api.mask_text(text, opts, mapping, auditor=auditor, report=_note)
                ops.write(out, masked)
                if out and out != "-":
                    api.bind_mapping_to_file(out, mapping)
        except (CliError, api.MaskError) as exc:
            print(exc, file=sys.stderr)
            return 2

        ops.save_mapping(mapping_path, mapping)
        print(f"замаскировано сущностей: {len(mapping['labels'])}; mapping: {mapping_path}",
              file=sys.stderr)
        if opts.org_names:
            CMD._report_org_dict(mapping, opts.org_names)
        return 0

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
    def _options(args: argparse.Namespace) -> Options:
        # Настройки Masker из флагов и пресета
        org_names = ()
        if getattr(args, "org_dict", None):
            from ..detection.recognizers.recognizers import load_org_dict

            org_names = load_org_dict(args.org_dict)
        supported_names = ()
        if getattr(args, "supported_names", None):
            lines = Path(args.supported_names).read_text(encoding="utf-8").splitlines()
            supported_names = tuple(line.strip() for line in lines if line.strip())

        ner_types = getattr(args, "ner_types", None)
        return Options(
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
        if kind not in _FILES:
            if args.file != "-":
                try:
                    api.validate_mapping_for_file(src_path, mapping)
                except api.MaskError as exc:
                    print(exc, file=sys.stderr)
                    return 2
            restored = api.unmask_text(ops.read(args.file), mapping)
            ops.write(args.output, restored)
            return 0

        # Книга, документ Word и презентация восстанавливаются в файл того же формата
        stem = src_path.stem.removesuffix(".masked")
        ext = kind if kind in api.LEGACY else src_path.suffix
        out = args.output or str(src_path.with_name(f"{stem}.unmasked{ext}"))
        if out == "-":
            print("файл этого формата нельзя писать в stdout - укажи -o файл", file=sys.stderr)
            return 2
        try:
            soffice = CMD._soffice(args) if kind in api.LEGACY else None
            api.unmask_file(src_path, out, mapping, soffice=soffice)
        except (CliError, api.MaskError) as exc:
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
