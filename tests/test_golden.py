"""Golden set: на эталонных документах с вымышленными ПД проверяем recall.

Правило: ни одна строка из MUST_MASK и ни один ее значимый кусок из FRAGMENTS не имеет
права дожить до замаскированного текста. Кусок ловит частичную утечку: "{{PERSON_1}}
Соколов" строку "Дмитрий Соколов" уже не содержит, а фамилию - содержит. Лишние маски
проверяются только списком MUST_KEEP - пропуск дороже лишней маски.
"""
import re
from pathlib import Path

import pytest

from pii_mask_enhanced.engine.core import Masker

GOLDEN = Path(__file__).parent / "golden"

_RESUME_PII = [
    "Смирнова Анна Валерьевна",
    "+7 (912) 3456789",
    "anna.smirnova.94@mail.example",
    "Северный Торговый Банк",
    "severbank-example.ru",
    "Новосибирский государственный технический университет",
    "Ковалев Игорь Петрович",
    "+7 (913) 7654321",
]
_RESUME_FRAGMENTS = ["Смирнов", "Ковалев", "anna.smirnova", "severbank", "3456789", "7654321",
                     "Торговый Банк"]

MUST_MASK = {
    # Одно содержание в двух формах: колоночная выгрузка из PDF и нормальный
    # markdown. Верстка не должна влиять на то, что считается персданными.
    "resume_hh_1.md": _RESUME_PII,
    "resume_md_1.md": _RESUME_PII,
    "transcript_1.md": [
        "Дмитрий Соколов",
        "ООО Ромашка",
        "Марина",
        "marina.k@romashka-corp.ru",
        "Соколову",
        "8 (916) 555-12-34",
        "Алексей Межов",
        "@a_mezhov",
        "Алексею",
        "Дмитрию Соколову",
    ],
    "contract_1.md": [
        "ООО «Северный Ветер»",
        "7707100002", "770701001", "1027700000008",
        "Белоусовой Марины Сергеевны", "М.С. Белоусова",
        "Воронцов Андрей Игоревич", "А.И. Воронцов",
        "40702810700000000005", "044525987", "30101810500000000002",
        "+7 (495) 123-45-67", "info@severveter-example.ru",
        "14.03.1988", "4510 № 654321", "770-001",
        "ул. Льва Толстого, д. 16, кв. 42", "ул. Тверская, д. 7",
        "540600000040", "112-345-600 06", "2200 0000 0000 0004",
        "+7 (916) 765-43-21", "a.vorontsov@mail.example",
    ],
    "hr_order_1.md": [
        "ЧЕРНЫХ ОЛЬГУ ПЕТРОВНУ", "О.П. Черных", "М.С. Белоусова", "00123", "185 000",
        "ООО «СЕВЕРНЫЙ ВЕТЕР»",
    ],
    "service_1.log": [
        "o.chernykh", "o.chernykh@severveter-example.ru", "203.0.113.47",
        "reports.severveter.local", "db.severveter.local", "eyJhbGciOiJIUzI1NiJ9", "S3cretPass",
        "report_user",
        "a.vorontsov@mail.example", "+7 916 765-43-21",
    ],
}

# Значимые куски значений: фамилии по основе (ловят и падежи), уникальные части адресов,
# цифры номеров - они проверяются по тексту без разделителей.
FRAGMENTS = {
    "resume_hh_1.md": _RESUME_FRAGMENTS,
    "resume_md_1.md": _RESUME_FRAGMENTS,
    "transcript_1.md": ["Соколов", "Межов", "Ромашка", "marina.k", "romashka-corp", "a_mezhov",
                        "5551234"],
    "contract_1.md": ["Белоусов", "Воронцов", "Северный Ветер", "severveter", "Толстого",
                      "Тверская", "Банк Пример", "14031988", "654321", "1234567", "7654321",
                      "11234560006", "2200000000000004"],
    "hr_order_1.md": ["Черных", "Белоусов", "СЕВЕРНЫЙ ВЕТЕР", "185000"],
    "service_1.log": ["chernykh", "vorontsov", "203.0.113", "S3cret", "7654321", "severveter"],
}

MUST_KEEP = {
    "transcript_1.md": ["Спикер 1", "Спикер 2", "Спикер 3", "[00:23]", "Транскрипт"],
    # Резюме: канцелярия и доменные термины - не ПД. Если они уходят под маску,
    # документ становится нечитаемым, а для показа человеку - непригодным.
    "resume_hh_1.md": [
        "Желаемая должность", "Специализации", "Аналитик", "полная занятость",
        "Data Mart", "Планирование", "Анализ данных", "Образование", "Навыки",
        "Финансовый сектор", "Руководитель направления клиентской аналитики",
    ],
    "resume_md_1.md": [
        "Желаемая должность", "Аналитик", "полная занятость", "Data Mart",
        "планирование", "Образование", "Навыки", "Руководитель направления клиентской аналитики",
    ],
    "contract_1.md": ["Договор оказания услуг", "Предмет договора", "150 000", "30 сентября 2026",
                      "аналитического отчета", "Реквизиты сторон", "генерального директора",
                      "«Заказчик»", "«Исполнитель»"],
    # дата приказа совпадает с датой трудового договора, но данными о договоре не становится
    "hr_order_1.md": ["ПРИКАЗ", "Табельный номер", "полная занятость", "испытательным сроком",
                      "Генеральный директор", "Финансовый отдел", "15.09.2026"],
    "service_1.log": ["2026-10-01 09:14:02", "GET /reports/17", "status=200", "nightly-export",
                      "Authorization: Bearer"],
}


# Что обязано вернуться при обратной подстановке дословно.
ROUNDTRIP = {
    "transcript_1.md": ["marina.k@romashka-corp.ru", "8 (916) 555-12-34"],
    "resume_hh_1.md": ["anna.smirnova.94@mail.example", "+7 (912) 3456789", "www.severbank-example.ru"],
    "resume_md_1.md": ["anna.smirnova.94@mail.example", "+7 (913) 7654321", "www.severbank-example.ru"],
    "contract_1.md": ["40702810700000000005", "112-345-600 06", "+7 (916) 765-43-21",
                      "a.vorontsov@mail.example", "14.03.1988"],
    "service_1.log": ["203.0.113.47", "S3cretPass", "o.chernykh@severveter-example.ru"],
}

# Имена возвращаются меткой в именительном падеже ("договор у Марина") и полной формой:
# одиночное "Дмитрий" связано с "Дмитрий Соколов" и возвращается им. Это поведение меток,
# а не потеря данных: проверяем, что вернулись нормальные формы и не осталось меток.
ROUNDTRIP_NAMES = {
    "transcript_1.md": ["Дмитрий Соколов", "Алексей Межов", "Марина"],
    "contract_1.md": ["Белоусовой Марины Сергеевны", "Воронцов Андрей Игоревич"],
}

# Одно лицо в разных падежах и формах - одна метка, и ни одна форма не остается открытой.
ONE_PERSON = [
    ("в лице директора Белоусовой Марины Сергеевны. Подписала Белоусова Марина Сергеевна.", "Белоусов"),
    ("в лице директора Петрова Ивана Сергеевича. Подписал Петров Иван Сергеевич. Позвонить Петрову.", "Петров"),
    ("в лице Сухаревой Алины Петровны. Подписала Сухарева Алина Петровна. Звонила Сухаревой.", "Сухарев"),
    ("от Черных Ольги Петровны. Подписала Черных Ольга Петровна.", "Черных"),   # несклоняемая фамилия
    ("Дмитрий Соколов пришел. Продублируй Соколову.", "Соколов"),
]


def _masked(fname: str) -> tuple[str, str, dict]:
    src = (GOLDEN / fname).read_text(encoding="utf-8")
    masked, mapping = Masker().mask(src)
    return src, masked, mapping


def _leaked_fragments(masked: str, fragments: list[str]) -> list[str]:
    low, digits = masked.lower(), re.sub(r"\D", "", masked)
    return [f for f in fragments if f.lower() in low or (f.isdigit() and f in digits)]


@pytest.mark.parametrize("fname", sorted(MUST_MASK))
def test_golden_recall(fname):
    _, masked, _ = _masked(fname)
    leaked = [s for s in MUST_MASK[fname] if s in masked]
    assert not leaked, f"утекло в masked: {leaked}"
    partial = _leaked_fragments(masked, FRAGMENTS[fname])
    assert not partial, f"утекли части значений: {partial}"
    kept_broken = [s for s in MUST_KEEP[fname] if s not in masked]
    assert not kept_broken, f"поломана структура: {kept_broken}"


@pytest.mark.parametrize("text, surname", ONE_PERSON)
def test_one_person_one_label(text, surname):
    masked, mapping = Masker().mask(text)
    assert sum(r["type"] == "PERSON" for r in mapping["labels"].values()) == 1, masked
    assert surname not in masked, f"осталась форма фамилии: {masked}"


@pytest.mark.parametrize("fname", sorted(ROUNDTRIP))
def test_golden_roundtrip(fname):
    _, masked, mapping = _masked(fname)
    restored = Masker(ner=False).unmask(masked, mapping)
    missing = [s for s in ROUNDTRIP[fname] if s not in restored]
    assert not missing, f"не вернулось при развороте: {missing}"


@pytest.mark.parametrize("fname", sorted(ROUNDTRIP_NAMES))
def test_golden_roundtrip_names(fname):
    _, masked, mapping = _masked(fname)
    restored = Masker(ner=False).unmask(masked, mapping)
    assert "{{" not in restored, "в восстановленном тексте остались метки"
    missing = [s for s in ROUNDTRIP_NAMES[fname] if s not in restored]
    assert not missing, f"не вернулись имена: {missing}"
