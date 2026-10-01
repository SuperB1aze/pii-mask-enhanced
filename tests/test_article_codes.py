"""Артикул товара - не реквизит и не человек.

Поймано на выгрузке магазина фильтров: в колонке номенклатуры маскировались
куски артикулов ("OZN7701234567" -> "OZN{{INN_1}}") и марки товаров как люди
("Аквабрис", "Ривалон", "Экотерм").
"""
from pii_mask_enhanced.engine.core import Masker

VALID_INN = "6083778353"       # проходит контрольную сумму


def _mask(text, **kw):
    return Masker(**kw).mask(text)[0]


def test_inn_glued_to_letters_is_article_not_inn():
    """ИНН, приклеенный к буквам, - часть артикула.

    Контрольную сумму случайный десятизначный номер проходит примерно в одном
    случае из одиннадцати, так что на сотнях артикулов совпадения неизбежны.
    Отличает их не сумма, а то, что настоящий ИНН стоит отдельным словом.
    """
    for code in (f"OZN{VALID_INN}", f"арт{VALID_INN}", f"{VALID_INN}XYZ"):
        assert _mask(code, types=("INN",)) == code


def test_standalone_inn_still_masked():
    assert "{{INN_" in _mask(VALID_INN, types=("INN",))
    assert "{{INN_" in _mask(f"ИНН {VALID_INN}", types=("INN",))
    assert "{{INN_" in _mask(f"ИНН: {VALID_INN}, КПП", types=("INN",))


def test_separator_does_not_make_it_an_article():
    """Дефис и скобка - обычные разделители, а не склейка с артикулом."""
    assert "{{INN_" in _mask(f"(ИНН {VALID_INN})", types=("INN",))


def test_brand_is_not_a_person_in_strict_mode():
    """Одиночная незнакомая марка - не человек, когда включён строгий режим."""
    for brand in ("Аквабрис", "Ривалон", "Экотерм", "Ниагарис", "Ветролюкс"):
        assert _mask(brand, types=("PERSON",), ner_person_needs_fio=True) == brand


def test_real_fio_survives_strict_mode():
    """Ограничение режима: настоящие ФИО терять нельзя.

    Строгий режим сравнивается с обычным, а не с идеалом: фамилию-прилагательное
    ("Заречная") распознаватель не включает в спан и БЕЗ него, так что требовать
    от режима большего, чем даёт базовое поведение, значит проверять не его.
    """
    for fio in ("Соколова Анна Владимировна",
                "Заречная Светлана Леонидовна",
                "Орлов Руслан Тахирович"):
        base = _mask(fio, types=("PERSON",))
        strict = _mask(fio, types=("PERSON",), ner_person_needs_fio=True)
        assert strict == base, f"строгий режим потерял человека: {fio}"
        assert "{{PERSON_" in strict


def test_single_known_surname_still_masked():
    """Одиночная фамилия, знакомая словарю, остаётся человеком.

    Именно этим она отличается от марки: у "Иванов" и "Смирнова" есть граммемы
    фамилии, у "Аквабрис" и "Ривалон" словарь не знает слова вовсе.
    """
    assert "{{PERSON_" in _mask("Иванов", types=("PERSON",), ner_person_needs_fio=True)
    # "Смирнова" в одиночку распознаватель не видит и без строгого режима -
    # это его собственный предел, а не цена режима.
    assert _mask("Смирнова", types=("PERSON",)) == "Смирнова"


# --- поддержка именем из самого документа ---

def test_supported_name_accepted_without_name_grammemes():
    """Опорное имя принимается, даже когда морфология его не подтверждает.

    Проверяем сам предикат, а не то, как распознаватель поделит конкретную
    строку: деление спана - его внутренняя причуда, и тест, построенный на ней,
    ломается от смены имени, ничего не говоря о правиле.

    Смысл правила: словарь не знает фамилию "Метелина" ровно так же, как не
    знает марку "Аквабрис", и отличает их только сам документ - тем, что назвал
    фамилию рядом с правовой формой.
    """
    from pii_mask_enhanced.detection.recognizers import Entity

    ent = Entity("PERSON", "Метелина", 0, 8, "метелина")
    strict = Masker(types=("PERSON",), ner_person_needs_fio=True)
    assert not strict._ner_org_ok(ent), "без поддержки незнакомая фамилия отсеивается"

    supported = Masker(types=("PERSON",), ner_person_needs_fio=True,
                       supported_names=("метелина",))
    assert supported._ner_org_ok(ent), "документ назвал её контрагентом - принимаем"


def test_unsupported_brand_still_dropped():
    """Марка поддержки не получает - её никто не называл контрагентом."""
    out = _mask("Аквабрис", types=("PERSON",), ner_person_needs_fio=True,
                supported_names=("метелина",))
    assert out == "Аквабрис"


def test_generic_product_word_not_a_person():
    """"Саше" - товар, но pymorphy читает его и как дательный падеж "Саша".

    Морфологией эти чтения не развести: у настоящих фамилий ("Иванов",
    "Соколов") тоже есть обычное чтение. Родовой термин - случай для STOP_TERMS,
    и он в отличие от марок сходится: общих слов конечное число.
    """
    assert _mask("Саше", types=("PERSON",), ner_person_needs_fio=True) == "Саше"


def test_bare_digits_are_article_not_inn_in_strict_mode():
    """Артикул с валидной контрольной суммой неотличим от ИНН без подписи."""
    for code in ("1063391630", "1093295606", "3206839701"):
        assert _mask(code, types=("INN",), inn_needs_label=True) == code


def test_labelled_inn_still_masked_in_strict_mode():
    assert "{{INN_" in _mask(f"ИНН {VALID_INN}", types=("INN",), inn_needs_label=True)
    assert "{{INN_" in _mask('ООО "Ромашка", ИНН 6083778353',
                             types=("INN", "ORG"), inn_needs_label=True)
