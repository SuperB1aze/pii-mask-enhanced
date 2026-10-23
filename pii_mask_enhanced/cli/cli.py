"""CLI: pii-mask mask|unmask.

Пайплайн транскриптов:
    1. pii-mask mask встреча.md -> встреча.masked.md + встреча.mapping.json
    masked уходит в облачную LLM, ответ сохраняется в answer.md
    2. pii-mask unmask answer.md --mapping встреча.mapping.json
"""
from __future__ import annotations

import argparse
import sys

from ..detection import presets
from ..engine.core import DEFAULT_TYPES
from .cmd import CMD

_CONFIG_HELP = ("файл настроек (дефолт - pii-mask.toml в текущем каталоге или пользовательский "
                "конфиг): [audit] url, model, timeout, keep_alive; [convert] soffice")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pii-mask", description="Маскировка ПД перед облачной LLM")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mask", help="замаскировать файл или stdin (-)")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="куда писать masked (дефолт <stem>.masked.<расширение исходника>, "
                        "для .pdf и файла без расширения - .masked.md, для stdin - stdout)")
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
    p.add_argument("--config", help=_CONFIG_HELP)
    p.set_defaults(func=CMD.cmd_mask)

    p = sub.add_parser("unmask", help="вернуть оригиналы в замаскированный файл или ответ модели")
    p.add_argument("file")
    p.add_argument("--mapping", required=True, help="файл mapping, созданный при маскировке")
    p.add_argument("-o", "--output",
                   help="дефолт: для текста - stdout, для .doc, .docx, .xls, .xlsx, .ppt и .pptx - "
                        "<stem>.unmasked.<расширение исходника>")
    p.add_argument("--config", help=_CONFIG_HELP)
    p.set_defaults(func=CMD.cmd_unmask)

    p = sub.add_parser("presets", help="какие наборы типов знает библиотека")
    p.set_defaults(func=CMD.cmd_presets)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":  # python -m pii_mask_enhanced.cli.cli
    main()
