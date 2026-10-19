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
    LabelledValue("ЕСИА ID", "PERSON_ID",
                  r"(?:ЕСИА|госуслуг\w*)(?:[ \t]+(?:ID|идентификатор\w*))?", grouped_digits(5, 15)),
    # идентификатор объекта в ИС банка: MDM ID, OID ("1.2.643.5.1", GUID)
    LabelledValue("ID в ИС банка", "PERSON_ID", r"MDM(?:[ \t]*(?:ID|ид\w*))?|OID", CODE),
    LabelledValue("табельный номер", "PERSON_ID", TAB_LABEL, CODE),
    # разделитель обязателен: "user experience", "account manager" - не логин
    LabelledValue("логин", "PERSON_ID",
                  r"логин|login|user[ _-]?name|user|имя[ \t]+пользователя"
                  r"|уч[её]тн\w*[ \t]+запис\w*|account|аккаунт",
                  # точка - только внутри: "логин: ivanov_i." - конец предложения
                  r"[\w@+-](?:[\w@+-]|\.(?=[\w@+-])){2,63}", needs_sep=True),
    LabelledValue("номер обращения", "PERSON_ID", r"обращени\w*[ \t]*№", CODE),
    LabelledValue("карта лояльности", "PERSON_ID",
                  r"карт\w*[ \t]+(?:лояльност\w*|клиент\w*|бонусн\w*|скидочн\w*|«[^»\n]{1,20}»)",
                  CODE),
    # ОСАГО с буквенной серией: "ХХХ 0123456789"
    LabelledValue("полис", "PERSON_ID", r"полис\w*(?:[ \t]+(?:ОМС|ДМС|ОСАГО|КАСКО))?",
                  rf"(?:[А-ЯЁA-Z]{{3}}[ \t]?)?{grouped_digits(9, 16)}"),
    LabelledValue("ЭЛН", "PERSON_ID",
                  r"ЭЛН|лист(?:ок|к\w*)[ \t]+нетрудоспособност\w*|больничн\w*(?:[ \t]+лист\w*)?",
                  r"\d{12}(?!\d)"),
    LabelledValue("счет депо", "PERSON_ID", r"(?:раздел\w*[ \t]+)?сч[её]т\w*[ \t]+депо", CODE),

    # Имя держателя карты
    LabelledValue("держатель карты", "PERSON",
                  r"(?:держател\w*|владел\w*)[ \t]+карт\w*|card[ \t]?holder(?:[ \t]+name)?"
                  r"|имя[ \t]+(?:на[ \t]+карт\w*|держател\w*)|name[ \t]+on[ \t]+card",
                  r"(?:[A-Z][A-Za-z'-]+(?:[ \t]+[A-Z][A-Za-z'.-]*){1,2}"
                  r"|[А-ЯЁ][а-яёА-ЯЁ-]+(?:[ \t]+[А-ЯЁ][а-яёА-ЯЁ.-]*){1,2})(?![\w])",
                  needs_sep=True),

    # "CVV-код", "код безопасности карты", "card verification value", "security code"
    LabelledValue("CVV", "SECRET",
                  r"(?:CVV2?|CVC2?|CAV2|CVP2|CVN2?|CID)(?:[ -]?код\w*)?"
                  r"|код\w*[ \t]+(?:безопасности|на[ \t]+оборот\w*)(?:[ \t]+карт\w*)?"
                  r"|card[ \t]+(?:verification|security)[ \t]+(?:value|code)|security[ \t]+code",
                  r"\d{3,4}(?!\d)"),
    # "ПИН-код карты", "пин-код от карты", "PIN code"
    LabelledValue("PIN", "SECRET",
                  r"(?:PIN|ПИН)(?:[ -]?(?:код\w*|code))?(?:[ \t]+(?:от[ \t]+)?карт\w*)?",
                  r"\d{4,6}(?!\d)"),
    # без кавычек: в JSON '"password": "Qwerty123"' закрывающая кавычка - не часть пароля
    LabelledValue("пароль", "SECRET", r"пароль|password|passwd|pwd", r"[^\s,;\"'`]{3,64}",
                  needs_sep=True),
    # "контрольный вопрос" без "ответ на"
    LabelledValue("кодовое слово", "SECRET",
                  r"(?:(?:кодов|секретн|контрольн)\w*[ \t]+(?:слов|фраз)\w*|слов\w*-парол\w*"
                  r"|ответ\w*[ \t]+на[ \t]+(?:контрольн|секретн)\w*[ \t]+вопрос\w*)"
                  r"(?:[ \t]+клиент\w*)?",
                  TO_LINE_END),

    # сведения о человеке
    # "пол" - и пол комнаты, поэтому двоеточие обязательно
    LabelledValue("пол", "PERSONAL", SEX_LABEL,
                  r"(?:[Мм]уж\w*|[Жж]ен\w*|[МмЖж]|[Mm]ale|[Ff]emale|[MF])\.?(?!\w)", needs_sep=True),
    # после двоеточия - любое значение, без него - только название
    LabelledValue("гражданство", "PERSONAL", r"гражданств\w*|citizenship|nationality", WORDS,
                  needs_sep=True),
    # "гражданином РФ", "гражданки Узбекистана": падежи одного человека; "граждан РФ",
    # "гражданам" - про группу, не про конкретного человека
    LabelledValue("гражданство без двоеточия", "PERSONAL",
                  r"(?<!паспорт )(?<!паспорта )(?<!паспорту )(?<!паспорте )(?<!паспортом )"
                  r"(?:гражданств\w*|граждан(?:ин(?:а|у|ом|е)?|к(?:а|и|е|у|ой)))",
                  rf"{COUNTRY}(?!\w)"),
    # национальность - специальная категория ПД (ст. 10 152-ФЗ); без подписи "русская кухня" не ПД
    LabelledValue("национальность", "PERSONAL", r"национальност\w*", WORDS, needs_sep=True),
    # судимость
    LabelledValue("судимость", "PERSONAL",
                  r"(?:сведени\w*[ \t]+о[ \t]+|наличи\w*[ \t]+)?судимост\w*", TO_LINE_END,
                  needs_sep=True),
    # здоровье - специальная категория ПД: поле анкеты или выписки до конца строки
    LabelledValue("здоровье", "PERSONAL",
                  r"(?:основн\w*[ \t]+|сопутствующ\w*[ \t]+|клиническ\w*[ \t]+)?диагноз\w*"
                  r"|(?:хроническ\w*[ \t]+)?заболевани\w*|состояни\w*[ \t]+здоровья"
                  r"|противопоказани\w*|аллерги\w*(?:[ \t]+на)?|аллергическ\w*[ \t]+реакци\w*"
                  r"|анамнез\w*|группа[ \t]+здоровья|инвалидност\w*",
                  TO_LINE_END, needs_sep=True),
    LabelledValue("аллергия на", "PERSONAL", r"аллерги\w*[ \t]+на", WORDS),
    # анкета госслужащего: "Классный чин", "Допуск к гостайне: имеется"
    LabelledValue("классный чин и допуск", "PERSONAL",
                  r"классн\w*[ \t]+чин\w*|допуск\w*(?:[ \t]+к[ \t]+(?:гостайн\w*"
                  r"|государственн\w*[ \t]+тайн\w*))?",
                  TO_LINE_END, needs_sep=True),
    LabelledValue("награды", "PERSONAL",
                  r"(?:государственн\w*[ \t]+|ведомственн\w*[ \t]+)?наград\w*"
                  r"(?:[ \t]*(?:,|и)[ \t]*(?:поощрени\w*|достижени\w*|звани\w*))?"
                  r"|достижени\w*[ \t]+и[ \t]+наград\w*|поощрени\w*(?:[ \t]+и[ \t]+наград\w*)?"
                  r"|почётн\w*[ \t]+звани\w*|почетн\w*[ \t]+звани\w*|награждени\w*",
                  TO_LINE_END, needs_sep=True),
    # категория лица в анкете. Голое "Категория:" - и категория товара, его не берем
    LabelledValue("категория лица", "PERSONAL",
                  r"(?:льготн\w*|социальн\w*)[ \t]+(?:категори\w*|статус\w*)"
                  r"|категори\w*[ \t]+(?:гражданина|граждан|получателя|льготника|заявителя)"
                  r"|льгот(?:а|ы)|статус\w*[ \t]+клиента",
                  TO_LINE_END, needs_sep=True),
    LabelledValue("по национальности", "PERSONAL", r"по[ \t]+национальности", WORDS),
    LabelledValue("семейное положение", "PERSONAL", r"семейн\w*[ \t]+положени\w*", WORDS,
                  needs_sep=True),
    LabelledValue("возраст", "PERSONAL", r"возраст\w*",
                  r"\d{1,3}(?:[ \t]*(?:лет|год\w*))?(?!\w)"),
    # Стаж: "стаж 12 лет", "трудовой стаж: 12 лет 3 мес. 5 дн.", "со стажем 7 лет".
    # Цифра - сразу за подписью: "стаж не менее 3 лет", "стаж от 3 лет" - требование вакансии
    LabelledValue("стаж", "PERSONAL", EXPERIENCE_LABEL, EXPERIENCE),
    # регистр не важен: "Капитан", "Доцент" в начале фразы
    LabelledValue("воинское звание", "PERSONAL", r"(?:воинск\w*[ \t]+)?звани\w*",
                  rf"(?i:{RANK})(?!\w)"),
    LabelledValue("ученая степень", "PERSONAL", r"уч[её]н\w*[ \t]+(?:степен\w*|звани\w*)",
                  rf"(?i:{DEGREE})(?!\w)"),
    # буквенная шкала - у юрлица, см. "рейтинг агентства" ниже
    LabelledValue("ПКР", "PERSONAL", PKR_LABEL, PKR_VALUE),

    # кредитный рейтинг юрлица
    LabelledValue("рейтинг агентства", "RATING", RATING_LABEL, RATING_SCALE),
    LabelledValue("внутренний рейтинг", "RATING", INNER_RATING_LABEL, INNER_RATING),

    # география: страна, регион, место рождения, адрес, индекс, код города, координаты.
    # Название места без подписи не ищем: "Банк России", "Москва - столица" - не ПД
    LabelledValue("страна", "ADDRESS", COUNTRY_LABEL, WORDS, needs_sep=True),
    LabelledValue("регион", "ADDRESS", REGION_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("место рождения", "ADDRESS",
                  r"мест\w*[ \t]+рождени\w*|place[ \t]+of[ \t]+birth", TO_LINE_END, needs_sep=True),
    LabelledValue("адрес", "ADDRESS", ADDRESS_LABEL, TO_LINE_END, needs_sep=True),
    LabelledValue("по адресу", "ADDRESS", AT_ADDRESS_LABEL, TO_LINE_END),
    # "Индекс 300026" без двоеточия - не адрес (tests/test_address_run)
    LabelledValue("почтовый индекс", "ADDRESS",
                  r"почтов\w*[ \t]+индекс\w*|индекс(?=[ \t]*:)", r"\d{6}(?!\d)", digits_key=True),
    # полный номер "тел. (495) 123-45-67" - телефон, а код без номера - место
    LabelledValue("код города", "ADDRESS", CITY_CODE_LABEL,
                  r"(?:\(\d{2,5}\)|\d{2,5}(?!\d))", digits_key=True),
    LabelledValue("код города у телефона", "ADDRESS", r"телефон\w*|тел\.?|факс",
                  r"\([3489]\d{2,4}\)(?![ \t-]*\d)", digits_key=True),
    LabelledValue("широта и долгота", "ADDRESS", r"широт\w*|долгот\w*|lat(?:itude)?|lon(?:gitude)?|lng",
                  r"[-−]?\d{1,3}(?:[.,]\d+)?°?(?:[ \t]?[NSEWСЮВЗ](?!\w))?", needs_sep=True),

    # доход и удержания человека; слова между подписью и суммой ("оклад в размере ...")
    # разбирает finders/requisites.incomes
    LabelledValue("доход", "INCOME", INCOME_LABEL, INCOME_AMOUNT),
    LabelledValue("остаток и задолженность", "BALANCE", BALANCE_LABEL, BALANCE_AMOUNT),

    # назначение платежа: рассказывает, кто, кому и за что платил
    LabelledValue("назначение платежа", "PAYMENT", r"назначени\w*[ \t]+платеж\w*",
                  TO_LINE_END),

    # Только с двоеточием - в резюме "## Желаемая должность" это заголовок раздела, а
    # "специальность "прикладная информатика"" - фраза. Набор resume их оставляет
    LabelledValue("должность", "POSITION",
                  r"(?:занимаем\w*[ \t]+)?должност\w*|професси\w*|род[ \t]+занятий",
                  TO_LINE_END, needs_sep=True),
    LabelledValue("специальность", "POSITION",
                  r"специальност\w*|направлени\w*[ \t]+подготовки", TO_LINE_END, needs_sep=True),

    # орган выдачи документа; после "выдан" за номером его разбирает engine/propagation
    LabelledValue("орган выдачи", "ISSUER", ISSUER_LABEL, ISSUER_NAME),
    LabelledValue("код подразделения", "ISSUER", UNIT_CODE_LABEL, r"\d{3}[ \t-]?\d{3}(?!\d)",
                  digits_key=True),
)
