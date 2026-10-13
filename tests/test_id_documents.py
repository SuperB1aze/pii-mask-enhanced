"""Документы личности и транспорта кроме паспорта РФ: загранпаспорт, военный билет,
водительское удостоверение, свидетельства ЗАГС, СТС, ПТС, паспорт моряка, трудовая
книжка, ВНЖ, РВП, разрешение на работу, патент, миграционная карта, виза.

Форматы у них короткие и общие ("75 1234567", "АБ 1234567"), поэтому номер берется
у слова документа. Без контекста узнаются только свидетельство ЗАГС и трудовая
книжка: римские цифры серии в обычном тексте не встречаются. Номера в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats.office_xml import cell_label_type


def _mask(text: str, preset: str | None = None) -> str:
    types = presets.get(preset).types if preset else Masker().types
    return Masker(types=tuple(types), ner=False).mask(text)[0]


@pytest.mark.parametrize("preset", [None, "accounting"])
@pytest.mark.parametrize("src, expected", [
    ("загранпаспорт 75 1234567", "загранпаспорт {{IDDOC_1}}"),
    ("заграничный паспорт серия 75 № 1234567", "заграничный паспорт серия {{IDDOC_1}}"),
    ("загранпаспорт 751234567", "загранпаспорт {{IDDOC_1}}"),
    ("Военный билет: серия АБ № 1234567", "Военный билет: серия {{IDDOC_1}}"),
    ("водительское удостоверение серия 99 12 № 345678",
     "водительское удостоверение серия {{IDDOC_1}}"),
    ("ВУ 77 АА 123456", "ВУ {{IDDOC_1}}"),
    ("свидетельство о рождении IV-МЮ 123456", "свидетельство о рождении {{IDDOC_1}}"),
    ("серия ХІ-АГ 123456", "серия {{IDDOC_1}}"),       # римские цифры кириллицей
    ("СТС 99 АА 123456", "СТС {{IDDOC_1}}"),
    ("СТС 99 12 345678", "СТС {{IDDOC_1}}"),
    ("ПТС 77 УО 123456", "ПТС {{IDDOC_1}}"),
    ("ЭПТС 164301012345678", "ЭПТС {{IDDOC_1}}"),
    ("паспорт транспортного средства 77 УО 123456", "паспорт транспортного средства {{IDDOC_1}}"),
    ("паспорт моряка МК 1234567", "паспорт моряка {{IDDOC_1}}"),
    ("удостоверение личности моряка РМ № 1234567", "удостоверение личности моряка {{IDDOC_1}}"),
    ("вид на жительство 82 № 1234567", "вид на жительство {{IDDOC_1}}"),
    ("ВНЖ 82 1234567", "ВНЖ {{IDDOC_1}}"),
    ("РВП 83 № 7654321", "РВП {{IDDOC_1}}"),
    ("разрешение на работу серия 77 № 1234567890", "разрешение на работу серия {{IDDOC_1}}"),
    ("Патент серия 77 № 1234567890", "Патент серия {{IDDOC_1}}"),
    ("миграционная карта 4617 1234567", "миграционная карта {{IDDOC_1}}"),
    ("виза: серия 24 № 1234567", "виза: серия {{IDDOC_1}}"),
    ("виза: 123456789", "виза: {{IDDOC_1}}"),
])
def test_document_masked(src, expected, preset):
    assert _mask(src, preset) == expected


@pytest.mark.parametrize("src", [
    "трудовая книжка ТК-IV 1234567",
    "вкладыш ВТ-I № 7654321",
    "серия АТ-IX 1234567",           # старый образец
    "ТК-IV 1234567",                 # формат узнается и без слова документа
])
def test_work_record_book(src):
    assert "{{IDDOC_1}}" in _mask(src)


def test_migration_cards_in_table_column():
    src = "Список: миграционные карты\n4617 1234567\n4618 7654321"
    assert _mask(src) == "Список: миграционные карты\n{{IDDOC_1}}\n{{IDDOC_2}}"


@pytest.mark.parametrize("src", [
    "патент № 2712345 на изобретение",
    "патент на изобретение выдан 12 3456789",
    "виза руководителя 123456789",
    "виза руководителя. Договор 24 1234567",   # "виза" - подпись согласования
    "визит 12 3456789",
    "ТК РФ статья 81",
])
def test_words_with_second_meaning_need_number_right_after(src):
    """У "патента" и "визы" есть второй смысл - номер берется только сразу за словом."""
    assert _mask(src) == src


def test_registration_certificate_without_context():
    """Свидетельство ЗАГС узнается по формату - слово документа рядом не нужно."""
    assert _mask("выдано II-ЖК № 654321") == "выдано {{IDDOC_1}}"


def test_document_word_in_table_header():
    """В таблице подпись в шапке колонки, а номера идут строками ниже."""
    src = "Серия и номер загранпаспорта\n\n75 1234567\n\n76 7654321\n"
    assert _mask(src) == "Серия и номер загранпаспорта\n\n{{IDDOC_1}}\n\n{{IDDOC_2}}\n"


def test_labelled_document_masked_everywhere():
    assert _mask("военный билет АБ 1234567. Позже указан АБ 1234567") == \
        "военный билет {{IDDOC_1}}. Позже указан {{IDDOC_1}}"


def test_driving_licence_is_not_a_passport():
    """Формат ВУ совпадает с паспортом - решает слово документа, а не слово "серия"."""
    assert "{{IDDOC_1}}" in _mask("водительское удостоверение серия 99 12 № 345678")
    assert _mask("паспорт серия 4509 № 123456") == "паспорт серия {{PASSPORT_1}}"


@pytest.mark.parametrize("src", [
    "заказ 75 1234567 отгружен",
    "артикул АБ 1234567",
    "ГОСТ 12 34 567890",
    "ВУЗ 99 12 345678",                 # "ВУ" - только отдельным словом
])
def test_lookalikes_untouched(src):
    assert _mask(src) == src


def test_solid_number_needs_document_word_right_before():
    """9 цифр подряд бывают и у БИК, и у КПП: слово документа в той же фразе - не довод."""
    src = "загранпаспорт оформлен. БИК 044525225, КПП 770101001"
    assert _mask(src) == src


def test_roundtrip_and_idempotent():
    m = Masker(ner=False)
    src = "Военный билет: серия АБ № 1234567"
    masked, mapping = m.mask(src)
    assert m.unmask(masked, mapping) == src
    assert m.mask(masked, mapping)[0] == masked


@pytest.mark.parametrize("label, value, expected", [
    ("Военный билет", "АБ 1234567", "IDDOC"),
    ("Серия и номер загранпаспорта", "75 1234567", "IDDOC"),
    ("Итого", "75 1234567", None),
])
def test_cell_label(label, value, expected):
    assert cell_label_type(label, value) == expected
