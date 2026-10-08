"""Обработчики подкоманд CLI: каждый принимает args и возвращает код выхода."""
from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

from ...detection import presets
from ...engine.core import DEFAULT_TYPES, Masker
from ...formats import xlsx
from .file_ops import FileOperations as ops


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
            if src_path is not None and kind == ".doc":
                return CMD.mask_legacy_doc(args, src_path)

            stem = src_path.with_suffix("") if src_path else None
            suffix = ".masked.xlsx" if kind == ".xlsx" else ".masked.docx" if kind == ".docx" else ".masked.md"
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
                if kind in (".xlsx", ".docx", ".pdf"):
                    return ops.probe_text(args.file, kind == ".xlsx", kind == ".docx", kind == ".pdf")
                try:
                    return source()
                except Exception:                     # noqa: BLE001
                    return None

            masker, org_names = CMD._build_masker(args, probe)
            mapping = ops.load_mapping(mapping_path)  # существующий mapping продолжаем

            if kind in (".xlsx", ".docx"):
                from ...formats import docx

                what = "книг" if kind == ".xlsx" else "документов Word"
                if args.audit:
                    raise CliError(f"--audit для {what} пока не поддержан: аудитор работает по тексту")
                if out is None or out == "-":
                    raise CliError("файл этого формата нельзя писать в stdout - укажи -o файл")
                run = xlsx.mask_workbook if kind == ".xlsx" else docx.mask_document
                mapping = run(args.file, out, masker, mapping)
            else:
                if kind == ".pdf":
                    # PDF читаем текстом и текстом же отдаем: собрать PDF обратно нельзя,
                    # замена другой длины ломает верстку строки (см. pii_mask_enhanced/formats/pdf.py).
                    from ...formats.pdf import PdfError, extract_text

                    try:
                        text = extract_text(args.file)
                    except PdfError as exc:
                        raise CliError(str(exc)) from exc
                else:
                    text = source()
                mask = masker.mask_with_audit if args.audit else masker.mask
                masked, mapping = mask(text, mapping)
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
    def mask_legacy_doc(args: argparse.Namespace, src_path: Path) -> int:
        # .doc переводится во временный .docx и маскируется как .docx. Имена
        # результата и реестра считаем от исходного файла.
        from ...formats.doc import DocError, as_docx

        stem = src_path.with_suffix("")
        out = args.output or f"{stem}.masked.docx"
        mapping_path = args.mapping or f"{stem}.mapping.json"
        CMD._check_paths((out, args.file, "результат и исходный файл"),
                         (mapping_path, args.file, "реестр и исходный файл"))
        try:
            with as_docx(src_path) as converted:
                inner = argparse.Namespace(**{**vars(args), "file": str(converted),
                                              "output": out, "mapping": mapping_path})
                return CMD.cmd_mask(inner)
        except DocError as exc:
            raise CliError(str(exc)) from exc

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
        def split(value: str) -> tuple[str, ...]:
            return tuple(x.strip().upper() for x in value.split(","))

        preset = None
        if getattr(args, "preset", None):
            try:
                preset, why = presets.resolve(args.preset,
                                              probe() if args.preset == presets.AUTO else None)
            except ValueError as exc:
                raise CliError(str(exc)) from exc
            print(why, file=sys.stderr)

        types = split(args.types) if args.types else preset.types if preset else DEFAULT_TYPES
        ner_types = split(args.ner_types) if getattr(args, "ner_types", None) else None

        org_names = ()
        if getattr(args, "org_dict", None):
            from ...detection.recognizers.recognizers import load_org_dict

            org_names = load_org_dict(args.org_dict)
        supported_names = ()
        if getattr(args, "supported_names", None):
            lines = Path(args.supported_names).read_text(encoding="utf-8").splitlines()
            supported_names = tuple(line.strip() for line in lines if line.strip())

        # флаг поверх набора добавляет строгость
        needs_form = getattr(args, "ner_org_needs_form", False) or bool(preset and preset.ner_org_needs_form)
        person_needs_fio = getattr(args, "ner_person_needs_fio", False) or bool(preset and preset.ner_person_needs_fio)
        inn_needs_label = getattr(args, "inn_needs_label", False) or bool(preset and preset.inn_needs_label)

        if needs_form and getattr(args, "auto_profile", False):
            # для 1С
            from ...detection import profile

            text = probe()
            if text is None:
                print("профиль: определить не удалось, остаюсь в строгом режиме", file=sys.stderr)
            else:
                print(profile.describe(text), file=sys.stderr)
                if profile.looks_like_resume(text):
                    needs_form = False

        masker = Masker(types=types, ner=not args.no_ner, org_names=org_names,
                        ner_types=ner_types,
                        ner_org_needs_form=needs_form,
                        ner_person_needs_fio=person_needs_fio,
                        supported_names=supported_names,
                        inn_needs_label=inn_needs_label)
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
        restored = Masker(ner=False).unmask(ops.read(args.file), mapping)
        ops.write(args.output, restored)
        return 0

    @staticmethod
    def cmd_serve(args: argparse.Namespace) -> int:
        import uvicorn

        from ..api.api import app

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0

    @staticmethod
    def cmd_presets(args: argparse.Namespace) -> int:
        for name in presets.names():
            preset = presets.get(name)
            print(f"{name} - {preset.title}")
            print(f"  типы: {','.join(preset.types)}")
            print(f"  организация только с правовой формой: "
                  f"{'да' if preset.ner_org_needs_form else 'нет'}")
        print(f"{presets.AUTO} - выбрать набор по профилю документа")
        return 0

    @staticmethod
    def cmd_where(args: argparse.Namespace) -> int:
        # путь импортированного модуля
        import pii_mask_enhanced

        print(pii_mask_enhanced.__file__)
        return 0
