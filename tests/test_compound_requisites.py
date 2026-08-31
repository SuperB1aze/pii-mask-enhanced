"""Составная подпись реквизитов: "ИНН/КПП 6083778353/770101001".

Поймано на счете от реального контрагента: одиночная подпись ("ИНН 7704...")
работала, а составная - нет, и ИНН уходил в обезличенный документ открытым.
Формы пишут парой, потому что КПП без ИНН не имеет смысла.
"""
from pii_mask.core import Masker

INN = "6083778353"
KPP = "770101001"


def _mask(text: str) -> str:
    return Masker(types=("INN", "OGRN"), inn_needs_label=True).mask(text)[0]


def test_compound_label_masks_inn():
    for text in (f"ИНН/КПП {INN}/{KPP}",
                 f"ИНН / КПП {INN} / {KPP}",
                 f"ИНН/КПП: {INN}/{KPP}",
                 f"ИНН и КПП {INN} / {KPP}"):
        out = _mask(text)
        assert INN not in out, f"ИНН остался открытым: {text!r} -> {out!r}"


def test_kpp_stays_visible():
    """КПП - не персональные данные: он у организации публичный и в types не входит.

    Маскировать его заодно значило бы выносить из документа смысл там, где риска нет.
    """
    assert KPP in _mask(f"ИНН/КПП {INN}/{KPP}")


def test_single_label_unchanged():
    """Прежнее поведение одиночной подписи не тронуто."""
    assert "{{INN_" in _mask(f"ИНН {INN}")
    assert "{{INN_" in _mask(f"ИНН: {INN}")


def test_pair_order_respected():
    """Пары сопоставляются по позиции: первый номер - первой подписи."""
    out = Masker(types=("INN",), inn_needs_label=True).mask(f"КПП/ИНН {KPP}/{INN}")[0]
    assert INN not in out and KPP in out


# --- формы из настоящего счета-фактуры ---

def test_qualifier_word_between_label_and_numbers():
    """В счете-фактуре подпись уточняется: "ИНН/КПП продавца"."""
    for text in (f"ИНН/КПП продавца     {INN} / {KPP}",
                 f"ИНН/КПП покупателя   {INN} / {KPP}"):
        assert INN not in _mask(text), f"не разобрано: {text!r}"


def test_missing_second_value():
    """У ИП нет КПП, и в форме остается висячий слэш: "194260834005 /"."""
    out = _mask("ИНН/КПП покупателя    194260834005 /")
    assert "194260834005" not in out


def test_number_confirmed_once_is_masked_everywhere():
    """Тот же номер ниже в документе повторяется уже без подписи.

    Подпись делает номер реквизитом для всего документа, а не для одной строки:
    иначе в счете-фактуре ИНН скрыт в шапке и открыт в блоке подписей.
    """
    text = (f"ИНН/КПП продавца   {INN} / {KPP}\n"
            f"Ромашка, ООО {INN} / {KPP}")
    out = _mask(text)
    assert INN not in out, "второе вхождение осталось открытым"


def test_unlabelled_number_alone_still_ignored():
    """Без подписи где-либо в документе число остается артикулом."""
    assert "1063391630" in _mask("Артикул 1063391630")
