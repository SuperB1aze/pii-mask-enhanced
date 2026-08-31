"""Ядро: mask/unmask со stateless mapping.

Принципы (см. дизайн-обсуждение):
- распознаватели только находят сущности, замену делает детерминированный код;
- одинаковая сущность (включая словоформы) -> одна метка на весь диалог;
- mapping возвращается вызывающему, сервис ничего не хранит;
- метка, которой не было во входе, при unmask превращается в UNKNOWN - защита
  от выдуманных моделью данных.

Форматные типы PHONE/EMAIL заменяются на формат-сохраняющие фейки
(+7 000 ... / userN@example.com), остальное - на метки {{TYPE_N}}.
"""
from __future__ import annotations

import copy
import re

from .recognizers import Entity, digits, find_format_entities

LABEL_RE = re.compile(r"\{\{([A-Z]+)_(\d+)\}\}")
PHONE_SCAN_RE = re.compile(r"\+?[78][\d \-()]{9,18}\d")
FAKE_EMAIL_SCAN_RE = re.compile(r"user\d+@example\.com", re.IGNORECASE)

UNKNOWN = "[неизвестное значение]"

DEFAULT_TYPES = (
    "PERSON", "ORG", "PHONE", "EMAIL", "CARD", "INN", "OGRN", "UID", "REQ",
    "SNILS", "PASSPORT", "TG", "URL", "ADDRESS",
)
# LOC (города/страны) сознательно не маскируем по умолчанию: в рабочих текстах
# это чаще контекст, чем ПД, и ложные маски убивают смысл. Включается через types.

_PRIORITY = {
    "EMAIL": 1, "TG": 2, "CARD": 3, "SNILS": 4, "PHONE": 5,
    "INN": 6, "OGRN": 6, "REQ": 6, "UID": 7, "PASSPORT": 7, "URL": 8,
    "ADDRESS": 8, "PERSON": 9, "ORG": 10, "LOC": 11,
}


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


class Masker:
    def __init__(
        self,
        types: tuple[str, ...] = DEFAULT_TYPES,
        ner: bool = True,
        org_names: tuple[str, ...] = (),
        ner_types: tuple[str, ...] | None = None,
        ner_org_needs_form: bool = False,
        ner_person_needs_fio: bool = False,
        supported_names: tuple[str, ...] = (),
        inn_needs_label: bool = False,
        trusted_numbers: frozenset[str] = frozenset(),
    ):
        self.types = set(types)
        # Каким типам верить со стороны NER. None - всем, что просили в types
        # (прежнее поведение). Ограничение нужно потому, что надежность
        # угадывания разная по типам: организацию в бухгалтерском документе
        # видно по правовой форме и без NER, а торговую марку он метит как
        # организацию и кромсает колонку товаров. ИП с ФИО, наоборот, кроме
        # него взять неоткуда.
        self.ner_types = None if ner_types is None else set(ner_types)
        # Принимать от NER организацию, только если в спане есть правовая форма
        # (ООО, ЗАО, ИП...). В бухгалтерском документе контрагент всегда с
        # формой, а торговая марка - никогда: "Nord Systems", "PureStream",
        # "IFalcon" уходили в маски и кромсали колонку товаров. Резать все
        # организации от NER нельзя - "ИП Заречная Светлана Леонидовна" он тоже
        # относит к организациям, и такие живые контрагенты утекали открытыми.
        self.ner_org_needs_form = ner_org_needs_form
        # Принимать от NER человека, только если спан похож на ФИО: хотя бы
        # один токен несёт граммемы имени, фамилии или отчества. Одиночная
        # незнакомая словарю марка ('Аквабрис', 'Ривалон', 'Экотерм') иначе
        # уходит в люди - в обычном тексте так и надо (экзотическое имя
        # дороже лишней маски), но в номенклатуре товаров это шум.
        self.ner_person_needs_fio = ner_person_needs_fio
        # Имена, которые документ сам объявил контрагентами - обычно тем,
        # что назвал их рядом с правовой формой ('ИП Метелина Лилия
        # Вячеславовна'). Строгий режим пропускает их даже без граммем
        # имени: словарь не знает фамилию 'Метелина' ровно так же, как не
        # знает марку 'Аквабрис', и отличает их только документ.
        self.supported_names = frozenset(n.lower() for n in supported_names)
        # Маскировать ИНН только рядом со словом ИНН. Голый десятизначный
        # номер с валидной контрольной суммой неотличим от артикула: сумму
        # случайное число проходит примерно в одном случае из одиннадцати,
        # и на тысяче артикулов совпадений набирается десятками. Цена
        # режима названа прямо: ИНН без подписи будет пропущен.
        self.inn_needs_label = inn_needs_label
        # Числа, у которых подпись реквизита стоит в соседней ячейке
        # таблицы: заполняется тем, кто видит книгу целиком.
        self.trusted_numbers = frozenset(trusted_numbers)
        wanted = self.types if self.ner_types is None else self.types & self.ner_types
        self._use_ner = ner and bool({"PERSON", "ORG", "LOC"} & wanted)
        # названия организаций, заданные снаружи (см. recognizers.load_org_dict)
        self.org_names = tuple(org_names)

    def _ner_org_ok(self, ent) -> bool:
        """Организация от NER: с правовой формой или без разницы.

        Правило касается ТОЛЬКО организаций и только тех, что предложил NER.
        Организации, найденные по форме детерминированно, и все прочие типы
        через эту проверку не проходят - она их не касается.
        """
        if ent.type == "ORG" and self.ner_org_needs_form:
            from .recognizers import ORG_FORM_RE

            return bool(ORG_FORM_RE.search(ent.text))
        if ent.type == "PERSON" and self.ner_person_needs_fio:
            from .ner import NatashaNer

            if self._supported(ent):
                return True
            return NatashaNer.shared().looks_like_person(ent.text)
        return True

    def _inn_ok(self, ent) -> bool:
        """ИНН без подписи в строгом режиме не принимается (см. inn_needs_label)."""
        if not self.inn_needs_label or ent.type != "INN":
            return True
        return ent.source != "bare" or ent.text.strip() in self.trusted_numbers

    def _supported(self, ent) -> bool:
        """Назвал ли документ это имя контрагентом (см. supported_names)."""
        if not self.supported_names:
            return False
        key = (ent.key or ent.text).lower()
        if key in self.supported_names:
            return True
        return any(tok in self.supported_names for tok in key.split())

    # --- mask ---

    def mask(
        self,
        text: str,
        mapping: dict | None = None,
        extra_entities: list[Entity] | None = None,
    ) -> tuple[str, dict]:
        mapping = copy.deepcopy(mapping) if mapping else {"version": 1, "labels": {}}
        labels: dict = mapping["labels"]

        candidates = [
            e for e in find_format_entities(text, self.org_names) if e.type in self.types
        ]
        if self._use_ner:
            from .ner import NatashaNer

            allowed = self.types if self.ner_types is None else self.types & self.ner_types
            candidates += [e for e in NatashaNer.shared().extract(text)
                           if e.type in allowed and self._ner_org_ok(e)]
        if extra_entities:
            # находки аудитора не фильтруем по types (раз LLM сочла это ПД - маскируем),
            # но отбрасываем наши же артефакты: метки и фейки не должны маскироваться
            # вторым слоем, иначе unmask разворачивает только верхний
            candidates += [e for e in extra_entities if not self._is_own_artifact(e.text)]

        # Номер, подписанный реквизитом ХОТЬ ГДЕ в тексте, считается реквизитом
        # везде: в счете-фактуре тот же ИНН стоит в шапке с подписью, а ниже в
        # блоке подписей - без нее, и построчная проверка скрыла бы только первое
        # вхождение.
        if self.inn_needs_label:
            confirmed = {e.text.strip() for e in candidates
                         if e.type == "INN" and e.source == "requisite"}
            candidates = [e for e in candidates
                          if self._inn_ok(e) or e.text.strip() in confirmed]

        # уже стоящие метки и спаны внутри них неприкосновенны (идемпотентность)
        occupied = [(m.start(), m.end()) for m in LABEL_RE.finditer(text)]
        accepted = self._resolve(candidates, occupied)

        replacements: list[tuple[int, int, str]] = []
        for ent in sorted(accepted, key=lambda e: e.start):
            placeholder = self._assign_label(labels, ent)
            replacements.append((ent.start, ent.end, placeholder))

        out, pos = [], 0
        for start, end, placeholder in replacements:
            out.append(text[pos:start])
            out.append(placeholder)
            pos = end
        out.append(text[pos:])
        return "".join(out), mapping

    @staticmethod
    def _resolve(candidates: list[Entity], occupied: list[tuple[int, int]]) -> list[Entity]:
        taken = list(occupied)
        accepted = []
        # Словарь идет первым разрядом ключа, до приоритета типа: название из
        # словаря назвал человек, и оно достовернее любой эвристики. Без этого
        # выигрывал тип с меньшим номером - NER объявлял "Ромашка Россия"
        # персоной, и словарное ORG проигрывало ему пересечение.
        ordered = sorted(
            candidates,
            key=lambda e: (
                0 if e.source == "dict" else 1,
                _PRIORITY.get(e.type, 99),
                -(e.end - e.start),
                e.start,
            ),
        )
        for ent in ordered:
            span = (ent.start, ent.end)
            if any(_overlaps(span, t) for t in taken):
                continue
            taken.append(span)
            accepted.append(ent)
        return accepted

    def _assign_label(self, labels: dict, ent: Entity) -> str:
        for placeholder, rec in labels.items():
            if rec["type"] == ent.type and (
                rec["key"] == ent.key or ent.key in rec.get("aliases", [])
            ):
                return placeholder

        # одиночное имя линкуем к единственному полному ФИО с этим токеном
        if ent.type == "PERSON" and " " not in ent.key:
            hosts = [
                (placeholder, rec)
                for placeholder, rec in labels.items()
                if rec["type"] == "PERSON" and " " in rec["key"] and ent.key in rec["key"].split()
            ]
            if len(hosts) == 1:
                placeholder, rec = hosts[0]
                rec.setdefault("aliases", []).append(ent.key)
                return placeholder

        n = 1 + max(
            (rec["n"] for rec in labels.values() if rec["type"] == ent.type), default=0
        )
        placeholder = self._make_placeholder(ent.type, n)
        original = ent.text
        # Лемму подставляем ТОЛЬКО для явно косвенной формы: иначе морфология
        # портит имя - женская фамилия "Смирнова" читается как родительный от
        # "Смирнов" и восстанавливалась бы мужской формой.
        if ent.type == "PERSON" and ent.oblique:
            original = ent.key.title()  # восстанавливать именительный падеж, не случайную словоформу
        labels[placeholder] = {"type": ent.type, "original": original, "key": ent.key, "n": n}
        return placeholder

    @staticmethod
    def _is_own_artifact(s: str) -> bool:
        from .recognizers import FAKE_EMAIL_RE

        s = s.strip()
        if LABEL_RE.search(s):
            return True
        if FAKE_EMAIL_RE.match(s):
            return True
        d = digits(s)
        return len(d) == 11 and d[1:4] == "000"

    @staticmethod
    def _make_placeholder(etype: str, n: int) -> str:
        if etype == "PHONE":
            return f"+7 000 000-{n // 100:02d}-{n % 100:02d}"
        if etype == "EMAIL":
            return f"user{n}@example.com"
        return f"{{{{{etype}_{n}}}}}"

    # --- unmask ---

    def mask_with_audit(self, text: str, mapping: dict | None = None) -> tuple[str, dict]:
        """mask + второй проход локальной LLM по уже замаскированному тексту.

        Fail-closed: если аудит запрошен, а Ollama недоступна - ошибка, а не
        тихий пропуск (вызывающий явно попросил повышенный recall).
        """
        from .auditor import audit, ollama_alive

        if not ollama_alive():
            raise RuntimeError(
                "запрошен --audit, но Ollama недоступна (PII_MASK_OLLAMA_URL); "
                "маскировка без аудита не выполнена намеренно"
            )
        masked, mapping = self.mask(text, mapping)
        extras = audit(masked)
        if extras:
            masked, mapping = self.mask(masked, mapping, extra_entities=extras)
        return masked, mapping

    def unmask(self, text: str, mapping: dict) -> str:
        labels: dict = mapping.get("labels", {})

        def sub_label(m: re.Match) -> str:
            rec = labels.get(m.group(0))
            return rec["original"] if rec else UNKNOWN

        text = LABEL_RE.sub(sub_label, text)

        phone_by_digits = {
            digits(placeholder): rec["original"]
            for placeholder, rec in labels.items()
            if rec["type"] == "PHONE"
        }

        def sub_phone(m: re.Match) -> str:
            d = digits(m.group(0))
            if d in phone_by_digits:
                return phone_by_digits[d]
            if d[1:4] == "000":  # выдуманный моделью номер из фейкового диапазона
                return UNKNOWN
            return m.group(0)

        text = PHONE_SCAN_RE.sub(sub_phone, text)

        def sub_email(m: re.Match) -> str:
            rec = labels.get(m.group(0).lower())
            return rec["original"] if rec else UNKNOWN

        text = FAKE_EMAIL_SCAN_RE.sub(sub_email, text)
        return text
