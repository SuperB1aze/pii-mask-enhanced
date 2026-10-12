"""Regex-распознаватели: форматные ПД РФ. Валидаторы контрольных сумм обязаны отсекать мусор."""
import pytest

from pii_mask_enhanced.detection.recognizers.recognizers import find_format_entities
from pii_mask_enhanced.detection.recognizers.validators import Validator


def types_of(text, wanted=None):
    ents = find_format_entities(text)
    if wanted:
        ents = [e for e in ents if e.type == wanted]
    return ents


# --- helpers: генерация валидных номеров ---

def make_inn10(base9: str) -> str:
    k = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    d = [int(c) for c in base9]
    return base9 + str(sum(a * b for a, b in zip(k, d)) % 11 % 10)


def make_snils(base9: str) -> str:
    d = [int(c) for c in base9]
    s = sum(d[i] * (9 - i) for i in range(9))
    if s < 100:
        chk = s
    elif s in (100, 101):
        chk = 0
    else:
        chk = s % 101
        if chk == 100:
            chk = 0
    return f"{base9[0:3]}-{base9[3:6]}-{base9[6:9]} {chk:02d}"


def digits_only(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


# --- PHONE ---

@pytest.mark.parametrize("raw", [
    "+7 903 123-45-67",
    "8 (903) 123-45-67",
    "89031234567",
    "+7-903-123-45-67",
    "8 903 123 45 67",
])
def test_phone_formats(raw):
    ents = types_of(f"позвони {raw} завтра", "PHONE")
    assert len(ents) == 1
    assert ents[0].text == raw


def test_phone_not_in_long_number():
    # 12+ цифр подряд - не телефон (например, счет)
    assert types_of("счет 407028103800001234567", "PHONE") == []


def test_phone_fake_range_not_rematched():
    # наш собственный фейковый диапазон +7 000 ... не должен маскироваться повторно
    assert types_of("тел +7 000 000-00-01", "PHONE") == []


# --- EMAIL / TG ---

def test_email():
    ents = types_of("пиши на ivan.petrov@company.example или в чат", "EMAIL")
    assert [e.text for e in ents] == ["ivan.petrov@company.example"]


def test_tg_handle():
    ents = types_of("мой ник @ivan_petrov77 в телеге", "TG")
    assert [e.text for e in ents] == ["@ivan_petrov77"]


def test_email_not_double_matched_as_tg():
    ents = find_format_entities("адрес ivan@example.org")
    assert {e.type for e in ents} == {"EMAIL"}


# --- INN ---

def test_inn10_valid():
    inn = make_inn10("770708389")
    ents = types_of(f"реквизит {inn} в карточке", "INN")
    assert [e.text for e in ents] == [inn]


def test_inn10_bad_checksum():
    inn = make_inn10("770708389")
    bad = inn[:-1] + str((int(inn[-1]) + 1) % 10)
    assert types_of(f"реквизит {bad} в карточке", "INN") == []


# --- SNILS ---

@pytest.mark.parametrize("base9", [
    "110704341",    # сумма 93 - контрольное число равно сумме
    "114143251",    # сумма 100 - контрольное 00
    "221105818",    # сумма 101 - контрольное 00
    "291417776",    # сумма 195 - остаток от деления на 101
    "820981233",    # сумма 201 - остаток 100 дает 00
])
def test_snils_valid(base9):
    # без подписи: с ней номер берется и с неверной суммой, и проверка суммы не видна
    sn = make_snils(base9)
    ents = types_of(f"номер {sn}", "SNILS")
    assert [e.text for e in ents] == [sn]


def test_snils_bad_checksum():
    sn = make_snils("112233445")
    bad = sn[:-2] + f"{(int(sn[-2:]) + 1) % 100:02d}"
    assert types_of(f"номер {bad}", "SNILS") == []


def test_snils_bad_checksum_with_label_masked_whole():
    # с подписью номер скрываем целиком, а не одну первую группу цифр
    sn = make_snils("112233445")
    bad = sn[:-2] + f"{(int(sn[-2:]) + 1) % 100:02d}"
    ents = types_of(f"СНИЛС: {bad}", "SNILS")
    assert [e.text for e in ents] == [bad]


@pytest.mark.parametrize("label", ["СНИЛС", "СНИЛС:", "СНИЛС №", "снилс"])
def test_snils_bare_with_label(label):
    sn = digits_only(make_snils("112233445"))
    ents = types_of(f"{label} {sn}", "SNILS")
    assert [e.text for e in ents] == [sn]


def test_snils_bare_without_label_skipped():
    sn = digits_only(make_snils("112233445"))
    assert types_of(f"номер {sn}", "SNILS") == []


def test_snils_bare_bad_checksum_with_label_not_snils():
    # слитный номер с неверной суммой у подписи - общий реквизит, но не СНИЛС
    sn = digits_only(make_snils("112233445"))
    bad = sn[:-1] + str((int(sn[-1]) + 1) % 10)
    assert types_of(f"СНИЛС {bad}", "SNILS") == []
    assert [e.text for e in types_of(f"СНИЛС {bad}", "REQ")] == [bad]


def test_snils_bare_phone_not_snils():
    assert types_of("тел. 89161234567", "SNILS") == []


# --- CARD (Луна) ---

def test_card_bad_luhn():
    assert types_of("номер 4111 1111 1111 1112", "CARD") == []


def make_card(body: str) -> str:
    return next(body + d for d in "0123456789" if Validator.luhn_ok(body + d))


def grouped(num: str, sizes: list[int]) -> str:
    out, i = [], 0
    for size in sizes:
        out.append(num[i:i + size])
        i += size
    return " ".join(out)


@pytest.mark.parametrize("raw", [
    grouped(make_card("427638001234567"), [4, 4, 4, 4]),
    "-".join(grouped(make_card("427638001234567"), [4, 4, 4, 4]).split()),
    "  ".join(grouped(make_card("427638001234567"), [4, 4, 4, 4]).split()),
    grouped(make_card("427638001234567"), [8, 8]),
    grouped(make_card("220012345678901234"), [4, 4, 4, 4, 3]),     # Мир, 19
    grouped(make_card("220012345678901234"), [6, 13]),
    make_card("22001234567890123"),                                # Мир, 18
    grouped(make_card("37828224631000"), [4, 6, 5]),               # Amex
    grouped(make_card("222100000000000"), [4, 4, 4, 4]),           # Mastercard 2221
    grouped(make_card("353011133330000"), [4, 4, 4, 4]),           # JCB
])
def test_card_formats_and_schemes(raw):
    ents = types_of(f"оплата {raw} принята", "CARD")
    assert [e.text for e in ents] == [raw]


@pytest.mark.parametrize("label", ["карта", "номер карты:", "карта Мир", "по карте №", "card"])
def test_card_bad_luhn_with_label(label):
    """С подписью номер с опечаткой в сумме - все равно карта."""
    ents = types_of(f"{label} 4111 1111 1111 1112", "CARD")
    assert [e.text for e in ents] == ["4111 1111 1111 1112"]


@pytest.mark.parametrize("src", [
    "штрихкод: 4607001234566",                                    # EAN-13
    "ОГРН 1027700132195",
    "ОГРНИП 304500116000157",
    "IMEI 490154203237518",                                       # Луна сходится, BIN чужой
    "р/с 40817810099910004312",
    "4081 7810 0999 1000 4312",
    "полис 7700000000000000",
    grouped(make_card("123456789012345"), [4, 4, 4, 4]),          # Луна есть, системы нет
    "итого 1 234 567 890 руб.",
])
def test_card_lookalikes_not_cards(src):
    assert types_of(src, "CARD") == []


# --- PASSPORT (только с контекстным словом) ---

def test_passport_with_context():
    ents = types_of("паспорт 4509 123456 выдан ОВД", "PASSPORT")
    assert [e.text for e in ents] == ["4509 123456"]


def test_passport_without_context():
    # без слова-триггера пара чисел - не паспорт (иначе FP на любой статистике)
    assert types_of("выпустили 4509 123456 единиц", "PASSPORT") == []


# --- URL / домен ---

def test_url_employer_domain_masked():
    """Сайт компании - такой же идентификатор, как ее название."""
    ents = types_of("Северный Торговый Банк, Москва, www.severbank-example.ru", "URL")
    assert [e.text for e in ents] == ["www.severbank-example.ru"]


def test_url_with_scheme_and_path():
    ents = types_of("Сайт https://severbank-example.ru/about устарел", "URL")
    assert [e.text for e in ents] == ["https://severbank-example.ru/about"]


def test_url_skips_technical_hosts():
    """Ссылка на репозиторий или документацию - не персданные, портить текст незачем."""
    src = "Код в github.com/dewil/pii-mask, справка docs.python.org/3/library/re.html"
    assert types_of(src, "URL") == []


def test_url_does_not_eat_filenames():
    """Молдова и Парагвай владеют доменами .md и .py - имена файлов под них не отдаем."""
    assert types_of("Правь core.py и README.md, смотри tests/test_api.py", "URL") == []


@pytest.mark.parametrize("src, url", [
    ("сайт президент.рф", "президент.рф"),
    ("портал госуслуги.рф/help", "госуслуги.рф/help"),
    ("www.кто-ты.рф", "www.кто-ты.рф"),
    ("сайт москва.рус", "москва.рус"),
    ("сайт xn--d1abbgf6aiiy.xn--p1ai", "xn--d1abbgf6aiiy.xn--p1ai"),
    ("site.su", "site.su"),
])
def test_url_cyrillic_and_punycode_domains(src, url):
    assert [e.text for e in types_of(src, "URL")] == [url]


@pytest.mark.parametrize("src, url", [
    ("наш сайт: example.shop", "example.shop"),
    ("сайт компании — пример.бел", "пример.бел"),
    ("ссылка на shop.tech/catalog", "shop.tech/catalog"),
    ("домен ivanov.dev", "ivanov.dev"),
    ("сайт: компания.москва", "компания.москва"),
])
def test_url_any_zone_after_hint(src, url):
    """Редкую зону берем только после слова-подсказки."""
    assert [e.text for e in types_of(src, "URL")] == [url]


@pytest.mark.parametrize("src", [
    "магазин example.shop",          # нет подсказки
    "г.Москва", "ул.Москва д.5", "сайт: г.москва",
    "т.е. всё", "и т.д.", "версия 3.10", "сайт обновлён 01.09.2026",
    "ссылка на отчет.pdf",
    "законодательство РФ.Статья 5",
])
def test_url_not_a_domain(src):
    assert types_of(src, "URL") == []


def test_url_with_scheme_found_once():
    ents = types_of("сайт https://президент.рф/news", "URL")
    assert [e.text for e in ents] == ["https://президент.рф/news"]


def test_url_does_not_swallow_email():
    ents = find_format_entities("почта hr@severbank-example.ru")
    assert [(e.type, e.text) for e in ents if e.type == "EMAIL"] == [
        ("EMAIL", "hr@severbank-example.ru")
    ]


# --- ОГРН / ОГРНИП ---

def make_ogrn13(base12: str) -> str:
    return base12 + str(int(base12) % 11 % 10)


def make_ogrn15(base14: str) -> str:
    return base14 + str(int(base14) % 13 % 10)


def test_ogrn13_valid():
    ogrn = make_ogrn13("102770006732")
    assert [e.text for e in types_of(f"реквизит {ogrn} в выписке", "OGRN")] == [ogrn]


def test_ogrn13_bad_checksum():
    ogrn = make_ogrn13("102770006732")
    bad = ogrn[:-1] + str((int(ogrn[-1]) + 1) % 10)
    assert types_of(f"реквизит {bad} в выписке", "OGRN") == []


def test_ogrnip15_valid():
    ogrnip = make_ogrn15("30477050030001")
    assert [e.text for e in types_of(f"реквизит {ogrnip} в выписке", "OGRN")] == [ogrnip]


def test_ogrn_not_confused_with_inn():
    """Границы по цифрам разводят типы: 13 знаков - не ИНН, 10 - не ОГРН."""
    ogrn = make_ogrn13("102770006732")
    assert types_of(f"реквизит {ogrn}", "INN") == []


# --- УИД договора (758-П) ---

def test_uid_uuid():
    uid = "3f2a9c14-5b6d-4e71-9a02-7c8de1f04b95"
    assert [e.text for e in types_of(f"УИД {uid} по договору", "UID")] == [uid]


def test_uid_with_part_number():
    uid = "3f2a9c14-5b6d-4e71-9a02-7c8de1f04b95-1"
    assert [e.text for e in types_of(f"запись {uid}", "UID")] == [uid]


def test_uid_needs_full_shape():
    """Обрывок хеша - не УИД: иначе маска ляжет на любой технический идентификатор."""
    assert types_of("хвост 09f4feeaa721-0 в колонке", "UID") == []


# --- ФИО капсом и инициалами (NER их не берет) ---

def test_caps_fio_full():
    ents = types_of("субъект ИВАНОВ ПЕТР СЕРГЕЕВИЧ включен в выборку", "PERSON")
    assert [e.text for e in ents] == ["ИВАНОВ ПЕТР СЕРГЕЕВИЧ"]


def test_caps_fio_name_first():
    ents = types_of("от ПЕТР СЕРГЕЕВИЧ ИВАНОВ поступило", "PERSON")
    assert [e.text for e in ents] == ["ПЕТР СЕРГЕЕВИЧ ИВАНОВ"]


def test_caps_fio_without_surname():
    ents = types_of("указан ПЕТР СЕРГЕЕВИЧ в графе", "PERSON")
    assert [e.text for e in ents] == ["ПЕТР СЕРГЕЕВИЧ"]


def test_caps_patronymic_alone_is_masked():
    """Отчество, оставшееся без соседей, - все равно часть имени."""
    ents = types_of("в графе указано\n\nСЕРГЕЕВИЧ\n\nдалее по списку", "PERSON")
    assert [e.text for e in ents] == ["СЕРГЕЕВИЧ"]


def test_caps_fio_spans_line_breaks():
    """В потоке из PDF ФИО идет по слову на строку - без переносов правило слепо."""
    ents = types_of("ИВАНОВ ПЕТР\nСЕРГЕЕВИЧ", "PERSON")
    assert [e.text for e in ents] == ["ИВАНОВ ПЕТР\nСЕРГЕЕВИЧ"]


def test_caps_heading_is_not_a_name():
    assert types_of("АКТ ПРОВЕРКИ ПО ОТДЕЛЬНОМУ ВОПРОСУ", "PERSON") == []


def test_caps_common_word_with_ich_is_not_patronymic():
    """Голое 'ИЧ' в набор суффиксов не входит - иначе КИРПИЧ становится персоной."""
    assert types_of("материал КИРПИЧ на складе", "PERSON") == []


def test_surname_with_initials():
    ents = types_of("Руководитель рабочей группы Страхова М.Е.", "PERSON")
    assert [e.text for e in ents] == ["Страхова М.Е."]


def test_initials_before_surname():
    ents = types_of("подписал М.Е. Страхова лично", "PERSON")
    assert [e.text for e in ents] == ["М.Е. Страхова"]


def test_caps_surname_with_initials():
    ents = types_of("СТРАХОВА М.Е.", "PERSON")
    assert [e.text for e in ents] == ["СТРАХОВА М.Е."]


def test_uid_wrapped_across_lines():
    """В колоночной верстке УИД рвется по дефису - строгий шаблон пропускал большинство."""
    src = "договор 3f2a9c14-5b6d-4e71-9a02-\n   7c8de1f04b95 в реестре"
    ents = types_of(src, "UID")
    assert len(ents) == 1 and ents[0].text.startswith("3f2a9c14")


def test_uid_head_without_tail():
    """Верстка теряет хвост УИД - голова из 20 знаков идентифицирует запись не хуже."""
    ents = types_of("в графе 3f2a9c14-5b6d-4e71-9a02-\nследующая строка", "UID")
    assert [e.text for e in ents] == ["3f2a9c14-5b6d-4e71-9a02-"]


def test_uid_does_not_eat_date_range():
    assert types_of("период 2019-2024 годы, бюджет 200-250", "UID") == []


# --- реквизит рядом с ключевым словом: контрольная сумма не нужна ---

def test_requisite_with_keyword_ignores_checksum():
    """Живой случай: '(ИНН 783199667)' - девять цифр вместо десяти. Валидатор такое
    отбрасывает, а компанию число называет ровно так же."""
    ents = types_of("Общество (ИНН 783199667) передало сведения", "INN")
    assert [e.text for e in ents] == ["783199667"]


def test_requisite_keeps_keyword_visible():
    from pii_mask_enhanced.engine.core import Masker
    masked, _ = Masker(types=("INN",), ner=False).mask("реквизиты: ИНН 783199667")
    assert masked == "реквизиты: ИНН {{INN_1}}"


def test_requisite_unknown_keyword_gets_own_type():
    """Реквизит без своего типа попадает в общий REQ.

    Пример сменен трижды: сперва с КПП на БИК (у КПП с 31.08.2026 свой тип), потом
    с БИК на ОКПО (у БИК свой тип с 02.09.2026 - иначе банковский блок счета
    оставался открытым, потому что REQ в бухгалтерских документах выключают),
    потом с ОКПО на ОКТМО (у ОКПО свой тип с 09.10.2026).
    Правило от этого не изменилось: незнакомая подпись по-прежнему дает REQ.
    """
    ents = types_of("ОКТМО 45382000 в карточке", "REQ")
    assert [e.text for e in ents] == ["45382000"]


# --- ОКПО ---

@pytest.mark.parametrize("num", [
    "12345678",        # юрлицо
    "10000640",        # оба прохода дали 10 -> контрольная 0
    "0123456789",      # ИП
    "1000000014",      # ИП, второй проход: 9-я цифра с весом 1, а не 11
    "10000000000001",  # обособленное подразделение
])
def test_okpo_checksum_accepts(num):
    assert Validator.okpo_ok(num)


@pytest.mark.parametrize("num", [
    "12345679",        # чужая контрольная
    "1000000013",      # так выходило с весами 3..11 без круга
    "044525225",       # 9 цифр - это БИК
    "1234567",
])
def test_okpo_checksum_rejects(num):
    assert not Validator.okpo_ok(num)


def test_okpo_labeled_gets_own_type():
    ents = types_of("ОКПО 12345678 в карточке", "OKPO")
    assert [e.text for e in ents] == ["12345678"]


def test_okpo_in_paired_requisites():
    ents = types_of("ИНН/КПП/ОКПО 7701234567/770101001/12345678", "OKPO")
    assert [e.text for e in ents] == ["12345678"]


def test_okpo_bad_checksum_falls_back_to_req():
    """Опечатка рядом с подписью - не повод оставить число открытым."""
    assert types_of("ОКПО 12345679", "OKPO") == []
    assert [e.text for e in types_of("ОКПО 12345679", "REQ")] == ["12345679"]


def test_okpo_bare_number_is_not_okpo():
    """Одна контрольная цифра: без подписи каждое десятое число сойдет за ОКПО."""
    assert types_of("заказ 12345678 отгружен", "OKPO") == []


def test_kpp_has_its_own_type():
    ents = types_of("КПП 770801001 в карточке", "KPP")
    assert [e.text for e in ents] == ["770801001"]


# --- организация: форма плюс кавычки ---

def test_org_form_with_quotes():
    ents = types_of("проверка АО «АЛЬФА-ПРИМЕР»            Банк", "ORG")
    assert [e.text for e in ents] == ["АО «АЛЬФА-ПРИМЕР»"]


@pytest.mark.parametrize("form", ["ФГБУ", "ГУП"])
def test_org_form_list_is_shared(form):
    """Формы, которые знала только книга Excel, работают и в тексте."""
    ents = types_of(f"заказчик {form} «Ромашка» по договору", "ORG")
    assert [e.text for e in ents] == [f"{form} «Ромашка»"]


def test_org_full_form_with_quotes():
    src = "Акционерное общество «Национальное бюро примеров» (ИНН"
    ents = types_of(src, "ORG")
    assert [e.text for e in ents] == ["Акционерное общество «Национальное бюро примеров»"]


def test_org_name_propagates_to_broken_layout():
    """Верстка режет название в таблице - но оно уже известно из полной формы."""
    src = (
        'договор с ООО «Эквипример Кредит»\n'
        '3.        «Эквипример Кредит      Дополнительное соглашение №6\n'
    )
    ents = types_of(src, "ORG")
    assert len(ents) >= 2
    assert any(e.text == "Эквипример" for e in ents)


def test_org_generic_words_do_not_propagate():
    """Родовые слова названия по документу не разносим - иначе маска на каждом 'бюро'."""
    src = "АО «Национальное бюро историй» ведет учет. Другое бюро отказало."
    ents = types_of(src, "ORG")
    assert all("Другое бюро" not in e.text for e in ents)
    assert not any(e.text.lower() == "бюро" for e in ents)


def test_registry_number_is_a_requisite():
    """В отраслевом реестре номер называет организацию не хуже ОГРН."""
    ents = types_of("КРЕДИТНАЯ ОРГАНИЗАЦИЯ, рег. № 1326", "REQ")
    assert [e.text for e in ents] == ["1326"]


def test_requisite_wrapped_after_keyword():
    """Карточка организации верстается узкой колонкой и рвется где попало."""
    ents = types_of("Идентификационный номер: КПП\n770801001.", "KPP")
    assert [e.text for e in ents] == ["770801001"]


def test_certificate_series_and_number():
    src = "зарегистрированном до 01.07.2002, серия 77\n№ 007893219)"
    ents = types_of(src, "REQ")
    assert [e.text for e in ents] == ["77", "007893219"]


def test_license_number_behind_a_phrase():
    src = "- Генеральная лицензия на осуществление банковских операций №1326 от\n16.01.2015"
    ents = types_of(src, "REQ")
    assert [e.text for e in ents] == ["1326"]


def test_registry_number_behind_a_phrase():
    src = "Регистрационный номер кредитной организации, присвоенный Банком\nРоссии: 1326."
    ents = types_of(src, "REQ")
    assert [e.text for e in ents] == ["1326"]


def test_dates_are_not_requisites():
    """Дата - основа смысла текста, по умолчанию не трогаем (см. README про --types)."""
    ents = find_format_entities("документ от 16.01.2015 и от 01.07.2002")
    assert ents == []


def test_passport_in_table_without_nearby_keyword():
    """В таблице слово стоит в шапке колонки, а номера идут сотнями строк ниже."""
    src = "серия, номер ДУЛ\n\n01.02.2020\n\n4509 123456\n\n15.03.2021\n\n4610 654321\n"
    ents = types_of(src, "PASSPORT")
    assert [e.text for e in ents] == ["4509 123456", "4610 654321"]


def test_surname_alone_after_full_fio_found():
    src = "ВЕРШКОВА ГАЛИНА ПЕТРОВНА в выборке\nГОРЛОВ\nВЕРШКОВА\n"
    ents = types_of(src, "PERSON")
    assert any(e.text == "ВЕРШКОВА" and e.start > 20 for e in ents)


def test_uid_without_inner_dashes():
    """Извлечение из PDF местами теряет внутренние дефисы."""
    ents = types_of("запись 3f2a9c14-5b6d4e719a027-1 в реестре", "UID")
    assert len(ents) == 1


def test_double_surname_fio():
    ents = types_of("НКУБА ЗАИМО\nЕКАТЕРИНА\nВИТАЛЬЕВНА в списке", "PERSON")
    assert ents and ents[0].text.startswith("НКУБА ЗАИМО")


def test_org_in_straight_quotes_split_by_wrap():
    ents = types_of('заемщик ООО\n"ПСКОВПРИМЕРДОР\nСТРОЙ" по договору', "ORG")
    assert ents and "ПСКОВПРИМЕРДОР" in ents[0].text


def test_truncated_word_masked_when_full_one_known():
    """Верстка режет ячейку по ширине: обрезок опознается по уже найденному слову."""
    ents = types_of("ИВАНОВ КОНСТАНТИН КОНСТАНТИНОВИЧ\nдалее\nКОНСТАНТИНОВИ", "PERSON")
    assert any(e.text == "КОНСТАНТИНОВИ" for e in ents)


# --- адрес и номера договоров ---

def test_address_with_index_and_wrap():
    src = "Местонахождение (юридическое/фактическое): 107078, г.\nМосква, ул. Каланчевская, д. 27."
    ents = types_of(src, "ADDRESS")
    assert len(ents) == 1 and ents[0].text.startswith("107078") and ents[0].text.endswith("27")


def test_address_street_word_after_name():
    ents = types_of("адрес 125009, г. Москва, Тверская ул., д. 1, стр. 2", "ADDRESS")
    assert len(ents) == 1 and ents[0].text.endswith("стр. 2")


def test_address_needs_both_anchors():
    """Слово улицы без номера дома и наоборот - не адрес, иначе маска на любой фразе."""
    assert types_of("шли по улице, дома 27 не нашли", "ADDRESS") == []
    assert types_of("проект сдан, дом 5 в плане", "ADDRESS") == []


def test_contract_number():
    """В номере договора часто сидит обломок названия стороны."""
    ents = types_of("по Договору №180517/01-ИУ и Договор №280206/РомашкаБ-И", "REQ")
    assert [e.text for e in ents] == ["180517/01-ИУ", "280206/РомашкаБ-И"]


def test_supplementary_agreement_number():
    ents = types_of("Дополнительное соглашение №6 от 01.07.2013", "REQ")
    assert [e.text for e in ents] == ["6"]
