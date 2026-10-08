"""CLI: pii-mask mask|unmask|serve.

Пайплайн транскриптов:
    1. pii-mask mask встреча.md -> встреча.masked.md + встреча.mapping.json
    masked уходит в облачную LLM, ответ сохраняется в answer.md
    2. pii-mask unmask answer.md --mapping встреча.mapping.json
"""
from __future__ import annotations

import argparse
import sys

from ...detection import presets
from ...engine.core import DEFAULT_TYPES
from .cmd import CMD


def main() -> None:
    parser = argparse.ArgumentParser(prog="pii-mask", description="Маскировка ПД перед облачной LLM")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mask", help="замаскировать файл или stdin (-)")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="куда писать masked (дефолт <stem>.masked.md, для stdin - stdout)")
    p.add_argument("--mapping", help="файл mapping (дефолт <stem>.mapping.json; существующий продолжается)")
    p.add_argument("--audit", action="store_true", help="второй проход локальной LLM (Ollama)")
    p.add_argument("--no-ner", action="store_true", help="без Natasha NER (только форматные ПД)")
    p.add_argument("--preset", choices=[*presets.names(), presets.AUTO],
                   help="именованный набор типов и строгости: "
                        + ", ".join(f"{n} - {presets.get(n).title}" for n in presets.names())
                        + f"; {presets.AUTO} - выбрать по документу")
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
    p.add_argument("--auto-profile", dest="auto_profile", action="store_true",
                   help="определить по документу, резюме это или деловая бумага, и "
                        "снять требование правовой формы для резюме "
                        "(действует только вместе с --ner-org-needs-form)")
    p.add_argument("--org-dict", dest="org_dict",
                   help="файл со списком названий организаций (по одному на строку); "
                        "нужен там, где у названия нет ни кавычек, ни орг-формы")
    p.set_defaults(func=CMD.cmd_mask)

    p = sub.add_parser("unmask", help="вернуть оригиналы в ответ модели")
    p.add_argument("file")
    p.add_argument("--mapping", required=True)
    p.add_argument("-o", "--output", help="дефолт stdout")
    p.set_defaults(func=CMD.cmd_unmask)

    p = sub.add_parser("presets", help="какие наборы типов знает сервис")
    p.set_defaults(func=CMD.cmd_presets)

    p = sub.add_parser("where", help="откуда работает код (путь импортированного модуля)")
    p.set_defaults(func=CMD.cmd_where)

    p = sub.add_parser("serve", help="поднять HTTP API (микросервис)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8377)
    p.set_defaults(func=CMD.cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":  # python -m pii_mask_enhanced.interfaces.cli.cli
    main()
