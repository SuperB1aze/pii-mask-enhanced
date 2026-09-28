"""CLI: pii-mask mask|unmask|serve.

Пайплайн транскриптов:
    pii-mask mask встреча.md              -> встреча.masked.md + встреча.mapping.json
    <masked уходит в облачную LLM, ответ сохраняется в answer.md>
    pii-mask unmask answer.md --mapping встреча.mapping.json

mapping-файл содержит оригиналы ПД: права 600, в git не коммитить (*.mapping.json
в .gitignore), удалять вместе с задачей.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import DEFAULT_TYPES, Masker


def _read(src: str) -> str:
    if src == "-":
        return sys.stdin.read()
    return Path(src).read_text(encoding="utf-8")


def _write(dst: str | None, content: str) -> None:
    if dst is None or dst == "-":
        sys.stdout.write(content)
        return
    Path(dst).write_text(content, encoding="utf-8")


def _load_mapping(path: str | None) -> dict | None:
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def _save_mapping(path: str, mapping: dict) -> None:
    p = Path(path)
    p.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(p, 0o600)


def cmd_mask(args: argparse.Namespace) -> int:
    if args.file == "-" and not args.mapping:
        print("для stdin обязателен --mapping", file=sys.stderr)
        return 2

    src_path = None if args.file == "-" else Path(args.file)
    is_book = src_path is not None and src_path.suffix.lower() == ".xlsx"
    is_pdf = src_path is not None and src_path.suffix.lower() == ".pdf"
    is_doc = src_path is not None and src_path.suffix.lower() == ".docx"
    stem = None if src_path is None else src_path.with_suffix("")
    # Книга остается книгой: отдать .md вместо .xlsx значит вернуть таблицу,
    # которую уже не открыть тем, чем ее прислали.
    suffix = (".masked.xlsx" if is_book else
              ".masked.docx" if is_doc else ".masked.md")
    out = args.output or (f"{stem}{suffix}" if stem else None)
    mapping_path = args.mapping or f"{stem}.mapping.json"

    # Пути считаются независимо, поэтому совпасть они могут молча: результат
    # успешно пишется, а следом затирается тем, что пишется вторым. Наружу это
    # выглядит как удачный прогон с кодом 0 и испорченным файлом.
    for a, b, what in ((out, mapping_path, "результат и реестр"),
                       (out, args.file, "результат и исходный файл"),
                       (mapping_path, args.file, "реестр и исходный файл")):
        if a and b and a != "-" and Path(a) == Path(b):
            print(f"{what} - один и тот же путь ({a}); один затрёт другой",
                  file=sys.stderr)
            return 2

    types = tuple(t.strip().upper() for t in args.types.split(",")) if args.types else DEFAULT_TYPES
    org_names = ()
    if getattr(args, "org_dict", None):
        from .recognizers import load_org_dict

        org_names = load_org_dict(args.org_dict)
    ner_types = (tuple(x.strip().upper() for x in args.ner_types.split(","))
                 if getattr(args, "ner_types", None) else None)
    supported_names = ()
    if getattr(args, 'supported_names', None):
        supported_names = tuple(
            line.strip() for line in Path(args.supported_names).read_text(
                encoding='utf-8').splitlines() if line.strip())
    masker = Masker(types=types, ner=not args.no_ner, org_names=org_names,
                    ner_types=ner_types,
                    ner_org_needs_form=getattr(args, 'ner_org_needs_form', False),
                    ner_person_needs_fio=getattr(args, 'ner_person_needs_fio', False),
                    supported_names=supported_names,
                    inn_needs_label=getattr(args, 'inn_needs_label', False))
    mapping = _load_mapping(mapping_path)  # существующий mapping продолжаем

    if is_book or is_doc:
        from . import docx, xlsx

        what = "книг" if is_book else "документов Word"
        if args.audit:
            print(f"--audit для {what} пока не поддержан: аудитор работает по тексту",
                  file=sys.stderr)
            return 2
        if out is None or out == "-":
            print(f"файл этого формата нельзя писать в stdout - укажи -o файл",
                  file=sys.stderr)
            return 2
        run = xlsx.mask_workbook if is_book else docx.mask_document
        mapping = run(args.file, out, masker, mapping)
    else:
        if is_pdf:
            # PDF читаем текстом и текстом же отдаем: собрать PDF обратно нельзя,
            # замена другой длины ломает верстку строки (см. pii_mask/pdf.py).
            from .pdf import PdfError, extract_text

            try:
                text = extract_text(args.file)
            except PdfError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        else:
            text = _read(args.file)
        if args.audit:
            masked, mapping = masker.mask_with_audit(text, mapping)
        else:
            masked, mapping = masker.mask(text, mapping)
        _write(out, masked)
    _save_mapping(mapping_path, mapping)
    n = len(mapping["labels"])
    print(f"замаскировано сущностей: {n}; mapping: {mapping_path}", file=sys.stderr)

    # Сколько записей словаря реально сработало. Без этой строки запись, не давшая
    # ни одного совпадения, ничем себя не выдает: словарь молчит одинаково и когда
    # он подошел к документу, и когда его составили не под этот текст.
    if org_names:
        used = {rec["key"] for rec in mapping["labels"].values() if rec["type"] == "ORG"}
        hit = [nm for nm in org_names if " ".join(nm.lower().split()) in used]
        print(f"словарь организаций: сработало {len(hit)} из {len(org_names)}", file=sys.stderr)
        if len(hit) < len(org_names):
            idle = [nm for nm in org_names if nm not in hit]
            shown = ", ".join(idle[:5]) + (f" и еще {len(idle) - 5}" if len(idle) > 5 else "")
            print(f"  не встретились в тексте: {shown}", file=sys.stderr)
    return 0


def cmd_unmask(args: argparse.Namespace) -> int:
    mapping = _load_mapping(args.mapping)
    if mapping is None:
        print(f"mapping не найден: {args.mapping}", file=sys.stderr)
        return 2
    restored = Masker(ner=False).unmask(_read(args.file), mapping)
    _write(args.output, restored)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_where() -> int:
    """Путь импортированного модуля, а не путь бинаря.

    Различие не формальное: бинарь может лежать где угодно, а код приходить из
    рабочего дерева разработчика, из удаленного каталога или из боевой копии -
    и снаружи эти случаи неразличимы.
    """
    import pii_mask

    print(pii_mask.__file__)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="pii-mask", description="Маскировка ПД перед облачной LLM")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mask", help="замаскировать файл или stdin (-)")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="куда писать masked (дефолт <stem>.masked.md, для stdin - stdout)")
    p.add_argument("--mapping", help="файл mapping (дефолт <stem>.mapping.json; существующий продолжается)")
    p.add_argument("--audit", action="store_true", help="второй проход локальной LLM (Ollama)")
    p.add_argument("--no-ner", action="store_true", help="без Natasha NER (только форматные ПД)")
    p.add_argument("--types", help=f"типы через запятую (дефолт {','.join(DEFAULT_TYPES)})")
    p.add_argument("--inn-needs-label", dest="inn_needs_label", action="store_true",
                   help="маскировать ИНН только рядом со словом ИНН: голый номер "
                        "с валидной контрольной суммой неотличим от артикула")
    p.add_argument("--supported-names", dest="supported_names",
                   help="файл с именами, которые документ объявил контрагентами "
                        "(по одному в строке): строгий режим пропускает их даже "
                        "без граммем имени")
    p.add_argument("--ner-person-needs-fio", dest="ner_person_needs_fio",
                   action="store_true",
                   help="человека от NER принимать, только если спан похож на ФИО: "
                        "отсекает одиночные марки товаров")
    p.add_argument("--ner-org-needs-form", dest="ner_org_needs_form",
                   action="store_true",
                   help="организацию от NER принимать только с правовой формой "
                        "(ООО, ЗАО, ИП): отсекает торговые марки в номенклатуре")
    p.add_argument("--ner-types", dest="ner_types",
                   help="каким типам верить со стороны NER (дефолт - всем из --types); напр. PERSON, чтобы марки товаров не уходили в организации")
    p.add_argument("--org-dict", dest="org_dict",
                   help="файл со списком названий организаций (по одному на строку); "
                        "нужен там, где у названия нет ни кавычек, ни орг-формы")
    p.set_defaults(func=cmd_mask)

    p = sub.add_parser("unmask", help="вернуть оригиналы в ответ модели")
    p.add_argument("file")
    p.add_argument("--mapping", required=True)
    p.add_argument("-o", "--output", help="дефолт stdout")
    p.set_defaults(func=cmd_unmask)

    p = sub.add_parser("where", help="откуда работает код (путь импортированного модуля)")
    p.set_defaults(func=lambda args: _cmd_where())

    p = sub.add_parser("serve", help="поднять HTTP API (микросервис)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8377)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":  # python -m pii_mask.cli
    main()
