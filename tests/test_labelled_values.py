"""Значения по подписи: ЕСИА ID, логин, полис, PIN, пароль, пол, гражданство...

Без подписи такое значение - просто число или слово, поэтому граница здесь - фразы,
где подпись есть, а значения нет: "логин выдается администратором", "пол деревянный".
Данные в тестах выдуманные.
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
    # идентификатор человека в системе
    ("ЕСИА ID: 1000123456", "ЕСИА ID: {{PERSON_ID_1}}"),
    ("Госуслуги идентификатор 1000123456", "Госуслуги идентификатор {{PERSON_ID_1}}"),
    ("MDM ID: 4567890123", "MDM ID: {{PERSON_ID_1}}"),
    ("OID: 4567890123", "OID: {{PERSON_ID_1}}"),
    ("OID 1.2.643.5.1", "OID {{PERSON_ID_1}}"),
    ("OID: 3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90", "OID: {{PERSON_ID_1}}"),
    ("таб. № 00123", "таб. № {{PERSON_ID_1}}"),
    ("логин: ivanov_i", "логин: {{PERSON_ID_1}}"),
    ("обращение № 2024-0012345 от клиента", "обращение № {{PERSON_ID_1}} от клиента"),
    ("карта лояльности 1234567890", "карта лояльности {{PERSON_ID_1}}"),
    ("полис ОМС 7700 0000 0000 0000", "полис ОМС {{PERSON_ID_1}}"),
    ("полис ОСАГО ХХХ 0123456789", "полис ОСАГО {{PERSON_ID_1}}"),
    ("листок нетрудоспособности № 910012345678", "листок нетрудоспособности № {{PERSON_ID_1}}"),
    ("счёт депо № 12345-Д", "счёт депо № {{PERSON_ID_1}}"),
    # секреты
    ("CVV: 123", "CVV: {{SECRET_1}}"),
    ("код на обороте 789", "код на обороте {{SECRET_1}}"),
    ("ПИН-код: 4821", "ПИН-код: {{SECRET_1}}"),
    ("ПИН-код карты: 4821", "ПИН-код карты: {{SECRET_1}}"),
    ("пин-код от карты 4821", "пин-код от карты {{SECRET_1}}"),
    ("PIN code 4821", "PIN code {{SECRET_1}}"),
    ("PIN-code: 4821", "PIN-code: {{SECRET_1}}"),
    ("CVV-код 123", "CVV-код {{SECRET_1}}"),
    ("CVV2/CVC2: 123", "CVV2/CVC2: {{SECRET_1}}"),
    ("код безопасности карты: 123", "код безопасности карты: {{SECRET_1}}"),
    ("card verification value: 123", "card verification value: {{SECRET_1}}"),
    ("security code: 1234", "security code: {{SECRET_1}}"),
    ("пароль: Qwerty123!", "пароль: {{SECRET_1}}"),
    ("кодовое слово: Барсик", "кодовое слово: {{SECRET_1}}"),
    ("кодовое слово клиента: Барсик", "кодовое слово клиента: {{SECRET_1}}"),
    ("секретное слово: Барсик", "секретное слово: {{SECRET_1}}"),
    ("контрольное слово Барсик", "контрольное слово {{SECRET_1}}"),
    ("кодовая фраза: синий кит", "кодовая фраза: {{SECRET_1}}"),
    ("слово-пароль: Барсик", "слово-пароль: {{SECRET_1}}"),
    ("ответ на контрольный вопрос: Барсик", "ответ на контрольный вопрос: {{SECRET_1}}"),
    # сведения о человеке
    ("пол: жен.", "пол: {{PERSONAL_1}}"),
    ("пол клиента: женский", "пол клиента: {{PERSONAL_1}}"),
    ("Пол ребёнка - мужской", "Пол ребёнка - {{PERSONAL_1}}"),
    ("половая принадлежность: мужская", "половая принадлежность: {{PERSONAL_1}}"),
    ("Gender: female", "Gender: {{PERSONAL_1}}"),
    ("sex: M", "sex: {{PERSONAL_1}}"),
    ("гражданство: Республика Беларусь", "гражданство: {{PERSONAL_1}}"),
    ("гражданство РФ", "гражданство {{PERSONAL_1}}"),
    ("семейное положение: не замужем", "семейное положение: {{PERSONAL_1}}"),
    ("возраст: 38 лет", "возраст: {{PERSONAL_1}}"),
    ("ПКР 812", "ПКР {{PERSONAL_1}}"),
    ("скоринговый балл: 650", "скоринговый балл: {{PERSONAL_1}}"),
    ("балл кредитной истории 720", "балл кредитной истории {{PERSONAL_1}}"),
    ("рейтинг в НБКИ: 812", "рейтинг в НБКИ: {{PERSONAL_1}}"),
    ("кредитный рейтинг: высокий", "кредитный рейтинг: {{PERSONAL_1}}"),
    # кредитный рейтинг юрлица
    ("кредитный рейтинг ruAA+", "кредитный рейтинг {{RATING_1}}"),
    ("рейтинг АКРА: AA-(RU)", "рейтинг АКРА: {{RATING_1}}"),
    ("рейтинг кредитоспособности НКР AA.ru", "рейтинг кредитоспособности НКР {{RATING_1}}"),
    ("кредитный рейтинг НРА AA|ru|", "кредитный рейтинг НРА {{RATING_1}}"),
    ("рейтинг эмитента от Moody's: Baa3", "рейтинг эмитента от Moody's: {{RATING_1}}"),
    ("присвоен рейтинг Эксперт РА на уровне ruBBB-, прогноз стабильный",
     "присвоен рейтинг Эксперт РА на уровне {{RATING_1}}, прогноз стабильный"),
    ("рейтинг S&P по международной шкале BBB-.",
     "рейтинг S&P по международной шкале {{RATING_1}}."),
    ("внутренний рейтинг заемщика: B2", "внутренний рейтинг заемщика: {{RATING_1}}"),
    ("класс кредитоспособности 2", "класс кредитоспособности {{RATING_1}}"),
    ("категория качества ссуды II", "категория качества ссуды {{RATING_1}}"),
    ("звание: старший лейтенант", "звание: {{PERSONAL_1}}"),
    ("Воинское звание: Капитан", "Воинское звание: {{PERSONAL_1}}"),
    ("учёная степень: кандидат технических наук", "учёная степень: {{PERSONAL_1}}"),
    ("Ученое звание: Доцент", "Ученое звание: {{PERSONAL_1}}"),
    # назначение платежа - целиком, вместе с тем, что внутри
    ("Назначение платежа: Оплата по счету 15 за услуги Иванова И.И., НДС не облагается",
     "Назначение платежа: {{PAYMENT_1}}"),
])
def test_value_after_label(src, expected, preset):
    assert _mask(src, preset) == expected


@pytest.mark.parametrize("src, expected", [
    ("является гражданином Российской Федерации", "является гражданином {{PERSONAL_1}}"),
    ("гражданки Узбекистана Петровой", "гражданки {{PERSONAL_1}} Петровой"),
    ("Citizenship: Russia", "Citizenship: {{PERSONAL_1}}"),
    ("Nationality: Belarus", "Nationality: {{PERSONAL_1}}"),
    ("национальность: русская", "национальность: {{PERSONAL_1}}"),
    ("по национальности татарин", "по национальности {{PERSONAL_1}}"),
    ("Иванов И.И., лицо без гражданства", "{{PERSON_1}}, {{PERSONAL_1}}"),
    ("иностранный гражданин Петров П.П.", "{{PERSONAL_1}} {{PERSON_1}}"),
])
def test_citizenship_forms(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "права граждан РФ",                             # множественное - про группу людей
    "гражданам Таджикистана",
    "иностранные граждане обязаны встать на учет",  # статус без человека рядом - текст закона
    "лицо без гражданства",
    "русская кухня",                                # национальность - только у подписи
])
def test_citizenship_lookalikes_untouched(src):
    assert _mask(src) == src


# --- логин ---

@pytest.mark.parametrize("src, expected", [
    ("Логин - ivanov_i", "Логин - {{PERSON_ID_1}}"),
    ("Логин\nivanov_i", "Логин\n{{PERSON_ID_1}}"),
    ("user=ivanov_i", "user={{PERSON_ID_1}}"),
    ("учетная запись: ivanov_i", "учетная запись: {{PERSON_ID_1}}"),
    ("account: ivanov_i", "account: {{PERSON_ID_1}}"),
    ('{"login": "ivanov_i", "password": "Qwerty123"}',
     '{"login": "{{PERSON_ID_1}}", "password": "{{SECRET_1}}"}'),
    ("логин/пароль: ivanov_i / Qwerty123", "логин/пароль: {{PERSON_ID_1}} / {{SECRET_1}}"),
    ("https://ivanov:Qwerty123@ftp.example.ru/files", "https://{{PERSON_ID_1}}:{{SECRET_1}}@{{URL_1}}"),
    (r"CORP\ivanov_i вошел в систему", "{{PERSON_ID_1}} вошел в систему"),
])
def test_login_forms(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "логин\nвыдается администратором",   # перенос фразы, а не поле анкеты
    "account manager Петров",            # без разделителя - не подпись
    r"C:\WINDOWS\system32",              # путь, а не доменная учетка
    r"\\SERVER\share",
    "вход под пользователем ivanov_i",   # без подписи логин не отличить от слова
])
def test_login_lookalikes(src):
    assert "{{PERSON_ID" not in _mask(src)


def test_cookie_uid_stays_session():
    """"uid" - имя cookie: значение остается сессией, а не логином."""
    assert _mask("Cookie: uid=abc123") == "Cookie: uid={{SESSION_1}}"


def test_citizenship_does_not_take_the_surname():
    """Страна - одно слово или устойчивое из двух; дальше уже фамилия."""
    assert _mask("гражданин Российской Федерации Белоусов") == "гражданин {{PERSONAL_1}} Белоусов"


def test_labelled_value_masked_everywhere():
    assert _mask("логин: ivanov_i. Вход под ivanov_i выполнен") == \
        "логин: {{PERSON_ID_1}}. Вход под {{PERSON_ID_1}} выполнен"


@pytest.mark.parametrize("src", [
    "логин выдается администратором",         # у логина и пароля нужен ":" или "="
    "пароль надо менять раз в квартал",
    "пол деревянный, 12 кв. м",                # "пол" без двоеточия - пол комнаты
    "пол: деревянный",                          # значения пола - закрытый список
    "пол помещения: деревянный",
    "sex education: course",
    "гражданство и место жительства",           # без двоеточия - только название страны
    "семейное положение влияет на вычет",
    "через Госуслуги 15 дней",
    "MDM система 2.0",
    "поле OID обязательно",
    "PIN-код выдается в отделении",
    "ПИН-кода нет",
    "CVV 12",                                   # 2 цифры - не CVV
    "PIN 1234567",                              # 7 цифр - не PIN
    "в возрасте до 18 лет",
    "Обращение к руководителю",
])
def test_label_without_value_untouched(src):
    assert _mask(src) == src


# --- должность и специальность: скрываются везде, кроме набора resume ---

POSITIONS = [
    ("Должность: ведущий инженер-конструктор отдела 12", "Должность: {{POSITION_1}}"),
    ("Занимаемая должность: главный бухгалтер", "Занимаемая должность: {{POSITION_1}}"),
    ("Профессия: электромонтер 4 разряда", "Профессия: {{POSITION_1}}"),
    ("Специальность: 08.03.01 Строительство", "Специальность: {{POSITION_1}}"),
]


@pytest.mark.parametrize("preset", [None, "accounting"])
@pytest.mark.parametrize("src, expected", POSITIONS)
def test_position_masked(src, expected, preset):
    from pii_mask_enhanced.engine.settings import Options, build_masker

    m, _ = build_masker(Options(preset=preset, ner=False), lambda: None)
    assert m.mask(src)[0] == expected


@pytest.mark.parametrize("src, _", POSITIONS)
def test_resume_preset_keeps_position(src, _):
    """Должность - содержание резюме: без нее модель не ответит о кандидате ничего."""
    from pii_mask_enhanced.engine.settings import Options, build_masker

    m, _ = build_masker(Options(preset="resume", ner=False), lambda: None)
    assert m.mask(src)[0] == src


def test_explicit_types_win_over_resume_preset():
    from pii_mask_enhanced.engine.settings import Options, build_masker

    m, _ = build_masker(Options(preset="resume", types=("POSITION",), ner=False), lambda: None)
    assert m.mask("Должность: аналитик")[0] == "Должность: {{POSITION_1}}"


@pytest.mark.parametrize("src", [
    "## Желаемая должность\n\nАналитик",           # заголовок раздела резюме, без двоеточия
    'специальность "прикладная информатика"',      # фраза
    "должность главного бухгалтера вакантна",
    "в лице генерального директора Иванова И.И.",  # роль представителя организации
])
def test_position_without_colon_untouched(src):
    assert "{{POSITION" not in _mask(src)


@pytest.mark.parametrize("label, value, expected", [
    ("Должность", "ведущий инженер", "POSITION"),
    ("Специальность", "08.03.01", "POSITION"),
    ("ЕСИА ID", "1000123456", "PERSON_ID"),
    ("OID", "1.2.643.5.1", "PERSON_ID"),
    ("Логин", "ivanov_i", "PERSON_ID"),
    ("Учетная запись", "ivanov_i", "PERSON_ID"),
    ("Пол", "жен.", "PERSONAL"),
    ("Звание", "капитан", "PERSONAL"),
    ("Учёная степень", "к.т.н.", "PERSONAL"),
    ("Звание", "мастер спорта", None),
    ("Назначение платежа", "Оплата по счету 15", "PAYMENT"),
    ("Итого", "1000123456", None),
])
def test_cell_label(label, value, expected):
    """Подпись в соседней ячейке таблицы - как в анкете или выписке 1С."""
    assert cell_label_type(label, value) == expected


def test_roundtrip_and_idempotent():
    m = Masker(ner=False)
    src = "ЕСИА ID: 1000123456\nпароль: Qwerty123!\nНазначение платежа: Оплата по счету 15"
    masked, mapping = m.mask(src)
    assert m.unmask(masked, mapping) == src
    assert m.mask(masked, mapping)[0] == masked
