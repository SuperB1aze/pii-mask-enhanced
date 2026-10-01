"""Ограничение слоя NER по типам: угадывание там, где оно надёжно.

Поймано на боевой номенклатуре: NER метит торговые марки как организации
("Nord Systems", "PureStream", "IFalcon"), и колонка товаров приходит
искромсанной. При этом организации в бухгалтерских документах всегда несут
правовую форму (ООО, ЗАО, АО) и ловятся детерминированно, без угадывания.
А вот ИП с ФИО без NER не поймать - там угадывание незаменимо.

Отсюда режим: NER работает, но его находки принимаются только по названным
типам.
"""
from pii_mask_enhanced.engine.core import Masker


def _mask(text: str, **kw) -> str:
    return Masker(types=("ORG", "PERSON"), **kw).mask(text)[0]


def test_brand_not_masked_when_ner_limited_to_person():
    for brand in ("Nord Systems", "PureStream", "IFalcon"):
        assert _mask(brand, ner_types=("PERSON",)) == brand


def test_legal_form_org_still_masked_without_ner_orgs():
    """Контрагент с правовой формой ловится правилом, а не угадыванием."""
    for org in ('ООО "Ромашка"', 'ЗАО "Василек"', "ООО «Ромашка»"):
        assert "{{ORG_" in _mask(org, ner_types=("PERSON",))


def test_individual_entrepreneur_still_masked():
    """Ради этого случая NER и остаётся включённым."""
    out = _mask("ИП Орлов Руслан Тахирович", ner_types=("PERSON",))
    assert "Орлов" not in out


def test_default_keeps_previous_behaviour():
    """Без ner_types поведение прежнее - NER отдаёт все свои типы."""
    assert "{{ORG_" in _mask("Nord Systems")


# --- организация от NER: только с правовой формой ---

def test_ner_org_without_legal_form_is_dropped():
    """Торговая марка - не контрагент: правовой формы у неё нет."""
    for brand in ("Nord Systems", "PureStream", "IFalcon"):
        assert _mask(brand, ner_org_needs_form=True) == brand


def test_ner_org_with_legal_form_survives():
    """ИП с ФИО распознаватель относит к организациям - и это живой контрагент.

    Ровно этот случай потерялся, когда организации от NER резались целиком:
    трое ИП ушли в обезличенную книгу открытым текстом.
    """
    for org in ("ИП Заречная Светлана Леонидовна",
                "ИП Метелина Лилия Вячеславовна",
                "ИП Ветрова Алевтина Серикбаевна"):
        out = _mask(org, ner_org_needs_form=True)
        assert org.split()[1] not in out, f"утёк живой контрагент: {org}"


def test_person_from_ner_untouched_by_org_rule():
    """Правило про форму касается только организаций."""
    out = _mask("Соколова Анна Владимировна", ner_org_needs_form=True)
    assert "Соколова" not in out
