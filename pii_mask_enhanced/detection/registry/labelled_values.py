"""Значения, которые узнаются только по подписи: "ЕСИА ID: 1000123456", "пол: жен."

Здесь - реестр: тип, подпись и формат значения. Сами регулярки - в registry/labelled_patterns.
"""
from __future__ import annotations

from dataclasses import dataclass

from .labelled_patterns import *


@dataclass(frozen=True)
class LabelledValue:
    name: str
    type: str
    # подпись
    label: str
    # значение за подписью; регистр важен
    value: str
    # подпись должна кончаться на ":" или "="
    needs_sep: bool = False
    # ключ по цифрам: счет слитно и группами - одно значение, одна метка
    digits_key: bool = False


VALUES = (
    LabelledValue("банковский счет", "ACCOUNT", ACCOUNT_LABEL, ACCOUNT_NUM, digits_key=True),
    # без подписи узнается только торговый код Мосбиржи (regulars.MOEX_CODE_RE)
    LabelledValue("код инвестора", "INVESTOR", INVESTOR_LABEL, INVESTOR_CODE),

    # идентификатор человека в чужой системе
    LabelledValue("ЕСИА ID", "PERSON_ID", ESIA_LABEL, ESIA_ID),
    LabelledValue("ID в ИС банка", "PERSON_ID", BANK_ID_LABEL, CODE),
    LabelledValue("табельный номер", "PERSON_ID", TAB_LABEL, CODE),
    LabelledValue("логин", "PERSON_ID", LOGIN_LABEL, LOGIN, needs_sep=True),
    LabelledValue("номер обращения", "PERSON_ID", APPEAL_LABEL, CODE),
    LabelledValue("карта лояльности", "PERSON_ID", LOYALTY_LABEL, CODE),
    LabelledValue("полис", "PERSON_ID", POLICY_LABEL, POLICY_NUM),
    LabelledValue("ЭЛН", "PERSON_ID", SICK_LEAVE_LABEL, SICK_LEAVE_NUM),
    LabelledValue("счет депо", "PERSON_ID", DEPO_LABEL, CODE),
    # серия и номер диплома и аттестата - в registry/id_documents
    LabelledValue("рег. номер диплома", "IDDOC", EDU_REG_LABEL, CODE),

    # карта и секреты
    LabelledValue("держатель карты", "PERSON", CARDHOLDER_LABEL, CARDHOLDER_NAME, needs_sep=True),
    LabelledValue("CVV", "SECRET", CVV_LABEL, CVV),
    LabelledValue("PIN", "SECRET", PIN_LABEL, PIN),
    LabelledValue("пароль", "SECRET", PASSWORD_LABEL, PASSWORD, needs_sep=True),
    LabelledValue("кодовое слово", "SECRET", CODE_WORD_LABEL, TO_LINE_END),

    # сведения о человеке
    LabelledValue("пол", "PERSONAL", SEX_LABEL, SEX_VALUE, needs_sep=True),
    # после двоеточия - любое значение, без него - только название страны
    LabelledValue("гражданство", "PERSONAL", CITIZENSHIP_LABEL, WORDS, needs_sep=True),
    LabelledValue("гражданство без двоеточия", "PERSONAL", CITIZEN_LABEL, CITIZEN_COUNTRY),
    # национальность - специальная категория ПД (ст. 10 152-ФЗ); без подписи "русская кухня" не ПД
    LabelledValue("национальность", "PERSONAL", NATIONALITY_LABEL, WORDS, needs_sep=True),
    # специальные категории - поле анкеты или выписки до конца строки; "не имеется" -
    # тоже сведения о человеке
    LabelledValue("судимость", "PERSONAL", CRIMINAL_FIELD_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("здоровье", "PERSONAL", HEALTH_FIELD_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("аллергия на", "PERSONAL", ALLERGY_LABEL, WORDS),
    # анкета госслужащего: "Классный чин", "Допуск к гостайне: имеется"
    LabelledValue("классный чин и допуск", "PERSONAL", CLEARANCE_FIELD_LABEL, TO_LINE_END,
                  needs_sep=True),
    LabelledValue("награды", "PERSONAL", AWARDS_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("категория лица", "PERSONAL", CATEGORY_FIELD_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("по национальности", "PERSONAL", BY_NATIONALITY_LABEL, WORDS),
    LabelledValue("семейное положение", "PERSONAL", MARITAL_LABEL, WORDS, needs_sep=True),
    LabelledValue("возраст", "PERSONAL", AGE_LABEL, AGE),
    LabelledValue("стаж", "PERSONAL", EXPERIENCE_LABEL, EXPERIENCE),
    LabelledValue("воинское звание", "PERSONAL", MILITARY_RANK_LABEL, MILITARY_RANK),
    LabelledValue("ученая степень", "PERSONAL", DEGREE_LABEL, DEGREE_VALUE),
    # буквенная шкала - у юрлица, см. "рейтинг агентства" ниже
    LabelledValue("ПКР", "PERSONAL", PKR_LABEL, PKR_VALUE),

    # кредитный рейтинг юрлица
    LabelledValue("рейтинг агентства", "RATING", RATING_LABEL, RATING_SCALE),
    LabelledValue("внутренний рейтинг", "RATING", INNER_RATING_LABEL, INNER_RATING),

    # география: страна, регион, место рождения, адрес, индекс, код города, координаты.
    # Название места без подписи не ищем: "Банк России", "Москва - столица" - не ПД
    LabelledValue("страна", "ADDRESS", COUNTRY_LABEL, WORDS, needs_sep=True),
    LabelledValue("регион", "ADDRESS", REGION_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("место рождения", "ADDRESS", BIRTHPLACE_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("адрес", "ADDRESS", ADDRESS_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("по адресу", "ADDRESS", AT_ADDRESS_LABEL, TO_LINE_END),
    LabelledValue("почтовый индекс", "ADDRESS", POSTCODE_LABEL, POSTCODE, digits_key=True),
    LabelledValue("код города", "ADDRESS", CITY_CODE_LABEL, CITY_CODE, digits_key=True),
    LabelledValue("код города у телефона", "ADDRESS", PHONE_FIELD_LABEL, PHONE_CITY_CODE,
                  digits_key=True),
    LabelledValue("широта и долгота", "ADDRESS", LATLON_LABEL, LATLON, needs_sep=True),

    # доход, удержания, остаток, долг и имущество; слова между подписью и суммой
    # ("оклад в размере ...") разбирает finders/requisites.incomes
    LabelledValue("доход", "INCOME", INCOME_LABEL, INCOME_AMOUNT),
    LabelledValue("остаток и задолженность", "BALANCE", BALANCE_LABEL, BALANCE_AMOUNT),

    # назначение платежа: рассказывает, кто, кому и за что платил
    LabelledValue("назначение платежа", "PAYMENT", PAYMENT_LABEL, TO_LINE_END),

    # должность и специальность; набор resume их оставляет
    LabelledValue("должность", "POSITION", POSITION_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("специальность", "POSITION", SPECIALTY_LABEL, TO_LINE_END, needs_sep=True),

    # орган выдачи документа; после "выдан" за номером его разбирает engine/propagation
    LabelledValue("орган выдачи", "ISSUER", ISSUER_LABEL, ISSUER_NAME),
    LabelledValue("код подразделения", "ISSUER", UNIT_CODE_LABEL, UNIT_CODE, digits_key=True),
)
