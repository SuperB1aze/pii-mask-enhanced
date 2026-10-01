"""Ядро: mask/unmask со stateless mapping.

Принципы:
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

from ..detection.recognizers import DATE_AFTER_RE, Entity, digits, find_format_entities

LABEL_RE = re.compile(r"\{\{([A-Z]+)_(\d+)\}\}")
PHONE_SCAN_RE = re.compile(r"\+?[78][\d \-()]{9,18}\d")
FAKE_EMAIL_SCAN_RE = re.compile(r"user\d+@example\.com", re.IGNORECASE)

UNKNOWN = "[неизвестное значение]"

# Типографские близнецы дефиса и пробела ломают токенизацию: неразрывный дефис 
# U+2011 превращает составное название в мусор, и распознаватель не видит ни
# организацию, ни стоящую рядом фамилию. 
# По этой причине нормализуем только текст, по которому мы ищем ПД

_TYPO_TWINS = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-",
               "\u00a0": " ", "\u202f": " ", "\u2007": " "}
_TYPO_RE = re.compile("[" + "".join(_TYPO_TWINS) + "]")


def _org_core(value: str) -> str:
    # Ядро названия организации без правовой формы и без склонения. Составные названия не берем.

    from ..detection.recognizers import ORG_FORM_RE

    core = ORG_FORM_RE.sub("", value).strip(" \t«»\"',.-")
    return core if core and " " not in core else ""


def normalize_for_analysis(text: str) -> str:
    """Свести типографские близнецы к простым символам, не меняя длину."""
    return _TYPO_RE.sub(lambda m: _TYPO_TWINS[m.group()], text)

DEFAULT_TYPES = (
    "PERSON", "ORG", "PHONE", "EMAIL", "CARD", "INN", "OGRN", "UID", "REQ",
    "SNILS", "PASSPORT", "TG", "URL", "ADDRESS",
)
# LOC (города/страны) не маскируем по умолчанию. Включается через types.

_PRIORITY = {
    "EMAIL": 1, "TG": 2, "CARD": 3, "SNILS": 4, "PHONE": 5,
    "INN": 6, "OGRN": 6, "KPP": 6, "REQ": 6, "DOCREF": 6, "DATE": 6,
    "BIK": 6, "ACCOUNT": 6,
    "CERT": 6, "UID": 7,
    "PASSPORT": 7, "URL": 8,
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
        # угадывания разная по типам.
        self.ner_types = None if ner_types is None else set(ner_types)
        # Принимать от NER организацию, только если в спане есть правовая форма (ООО, ЗАО, ИП...).
        self.ner_org_needs_form = ner_org_needs_form
        # Принимать от NER человека, только если спан похож на ФИО
        self.ner_person_needs_fio = ner_person_needs_fio
        # Имена, которые документ сам объявил контрагентами
        self.supported_names = frozenset(n.lower() for n in supported_names)
        # Маскировать ИНН только рядом со словом ИНН
        self.inn_needs_label = inn_needs_label
        # Числа, у которых подпись реквизита стоит в соседней ячейке таблицы.
        self.trusted_numbers = frozenset(trusted_numbers)
        wanted = self.types if self.ner_types is None else self.types & self.ner_types
        self._use_ner = ner and bool({"PERSON", "ORG", "LOC"} & wanted)
        # названия организаций, заданные снаружи (см. recognizers.load_org_dict)
        self.org_names = tuple(org_names)

    def _ner_org_ok(self, ent) -> bool:
        # Организация от NER: с правовой формой или без разницы. Правило касается ТОЛЬКО организаций и только тех, что предложил NER.
        if ent.type == "ORG" and self.ner_org_needs_form:
            from ..detection.recognizers import ORG_FORM_RE

            return bool(ORG_FORM_RE.search(ent.text))
        if ent.type == "PERSON" and self.ner_person_needs_fio:
            from ..detection.ner import NatashaNer

            if self._supported(ent):
                return True
            return NatashaNer.shared().looks_like_person(ent.text)
        return True

    def _person_token_repeats(self, text: str, known: list) -> list:
        """Находит незамаскированные повторы слов из уже найденных ФИО.

        Например, отдельное "Иванов" после "Иванов Петр Сергеевич"; слова
        короче 4 букв не ищем, иначе закроем случайные "О." или "ИП".
        """
        if "PERSON" not in self.types:
            return []
        from ..detection.ner import _is_stop_term

        taken = {(e.start, e.end) for e in known}
        tokens = set()
        for ent in known:
            if ent.type != "PERSON":
                continue
            for tok in ent.text.replace(",", " ").split():
                tok = tok.strip(".,;:()\"'\u00ab\u00bb")
                if len(tok) >= 4 and tok[:1].isupper() and not _is_stop_term(tok):
                    tokens.add(tok)
        out = []
        for tok in tokens:
            for m in re.finditer(rf"(?<![\w-]){re.escape(tok)}(?![\w-])", text):
                if (m.start(), m.end()) in taken:
                    continue
                out.append(Entity("PERSON", tok, m.start(), m.end(),
                                  tok.lower(), source="person-token"))
        return out

    def _dates_after_docrefs(self, text: str, known: list) -> list:
        # Дата сразу за номером документа
        if "DATE" not in self.types:
            return []
        out = []
        for ent in known:
            if ent.type != "DOCREF":
                continue
            m = DATE_AFTER_RE.match(text, ent.end)
            if m:
                out.append(Entity("DATE", m.group(1), m.start(1), m.end(1),
                                  m.group(1).lower(), source="docdate"))
        return out

    @staticmethod
    def _repeats(text: str, values: set[str], known: list) -> list:
        # Повторные вхождения уже опознанных значений, которых нет среди находок.

        taken = {(e.start, e.end) for e in known}
        by_value = {}
        for e in known:
            by_value.setdefault(e.text.strip(), e)
        out = []
        for value in values:
            if len(value) < 3:
                continue        # два знака встречаются в тексте случайно
            src = by_value[value]
            start = 0
            while True:
                at = text.find(value, start)
                if at < 0:
                    break
                start = at + len(value)
                if (at, start) in taken:
                    continue
                before = text[at - 1] if at else " "
                after = text[start] if start < len(text) else " "
                # Только целым токеном: иначе номер найдется внутри другого числа.
                # Исключение - "г" сразу за датой ("01.09.2026г.")
                tail_year = (src.type == "DATE" and after in "гГ"
                             and text[start + 1: start + 2] in {".", "", " ", "\n", ","})
                if before.isalnum() or (after.isalnum() and not tail_year):
                    continue
                if tail_year:
                    start += 2 if text[start + 1: start + 2] == "." else 1
                    value_here = text[at:start]
                    out.append(Entity(src.type, value_here, at, start, src.key))
                    continue
                out.append(Entity(src.type, value, at, start, src.key))
        return out

    # Второе имя сразу за названием: "Ромашка (Romashka)", "Агентство ... (АСИ)", скрытое за скобкой
    _ALIAS_RE = re.compile(r"[ \t]*\(([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9 .&-]{1,30})\)")

    @staticmethod
    def _bracket_aliases(text: str, known: list) -> list:
        out = []
        for src in known:
            if src.type != "ORG":
                continue
            m = Masker._ALIAS_RE.match(text, src.end)
            if not m:
                continue
            alias = m.group(1).strip()
            # если больше трёх слов в скобках, то это пояснение
            if len(alias.split()) > 3:
                continue
            out.append(Entity("ORG", alias, m.start(1), m.end(1), src.key))
        return out

    def _without_geo_persons(self, candidates: list) -> list:
        # Убрать персоны, начатые географическим названием.
        # Пример: "России Б.Н. Ельцина" приняло за фамилию страну, проверка убирает метку

        if not self._use_ner:
            return candidates
        from ..detection.ner import NatashaNer

        ner = NatashaNer.shared()
        out = []
        for ent in candidates:
            if ent.type == "PERSON":
                head = ent.text.strip().split()[0] if ent.text.strip() else ""
                if head and ner.is_geography(head):
                    continue
            out.append(ent)
        return out

    def _org_token_repeats(self, text: str, known: list) -> list:
        # Слова подтвержденных названий, оставшиеся открытыми в других местах
        from ..detection.ner import STOP_TERMS, NatashaNer

        if not self._use_ner:
            # без NER подтвержденные названия приходят из словаря и по правовой форме
            return []
        ner = NatashaNer.shared()
        taken = {(e.start, e.end) for e in known}
        tokens: dict[str, object] = {}
        for src in known:
            if src.type != "ORG":
                continue
            # аббревиатуру капсом берем от трех знаков, обычное слово от пяти
            words = (re.findall(r"\b[А-ЯЁA-Z]{3,}\b", src.text)
                     + re.findall(r"[А-ЯЁA-Z][\w-]{4,}", src.text))
            for word in words:
                if word.lower() in STOP_TERMS or ner.known_common_word(word):
                    continue
                tokens.setdefault(word, src)
        out = []
        for word, src in tokens.items():
            # аббревиатура не укорачивается
            stem = (word if word.isupper()
                    else word[:-1] if word[-1].lower() in "аеёиоуыэюяьй" else word)
            if len(stem) < (3 if word.isupper() else 5):
                continue
            for m in re.finditer(re.escape(stem) + r"[а-яёa-z]{0,3}\b", text):
                if (m.start(), m.end()) in taken:
                    continue
                if m.start() and (text[m.start() - 1].isalnum()
                                  or text[m.start() - 1] in "-_"):
                    continue
                out.append(Entity(src.type, m.group(), m.start(), m.end(), src.key))
        return out

    @staticmethod
    def _org_case_repeats(text: str, known: list) -> list:
        # Подтвержденная организация в косвенном падеже.
        taken = {(e.start, e.end) for e in known}
        out = []
        for src in known:
            if src.type != "ORG" or len(src.text.strip()) < 5:
                continue
            value = _org_core(src.text)
            if not value:
                continue
            # склонение меняет окончание, поэтому ищем по основе без последней буквы
            stem = value[:-1] if value[-1].lower() in "аеёиоуыэюяьй" else value
            if len(stem) < 5:
                continue
            for m in re.finditer(re.escape(stem) + r"[а-яё]{0,3}\b", text):
                if (m.start(), m.end()) in taken:
                    continue
                if m.start() and text[m.start() - 1].isalnum():
                    continue
                out.append(Entity(src.type, m.group(), m.start(), m.end(), src.key))
        return out

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

    # --- unmask ---

    def mask(
        self,
        text: str,
        mapping: dict | None = None,
        extra_entities: list[Entity] | None = None,
    ) -> tuple[str, dict]:
        mapping = copy.deepcopy(mapping) if mapping else {"version": 1, "labels": {}}
        labels: dict = mapping["labels"]

        # Ищем по нормализованному тексту, отдаем исходный (см. _TYPO_TWINS).
        source = text
        text = normalize_for_analysis(text)

        candidates = [
            e for e in find_format_entities(text, self.org_names) if e.type in self.types
        ]
        if self._use_ner:
            from ..detection.ner import NatashaNer

            allowed = self.types if self.ner_types is None else self.types & self.ner_types
            candidates += [e for e in NatashaNer.shared().extract(text)
                           if e.type in allowed and self._ner_org_ok(e)]
        if extra_entities:
            candidates += [e for e in extra_entities if not self._is_own_artifact(e.text)]

        # номер, подписанный реквизитом где угодно в тексте, считается реквизитом везде
        if self.inn_needs_label:
            confirmed = {e.text.strip() for e in candidates
                         if e.type == "INN" and e.source == "requisite"}
            candidates = [e for e in candidates
                          if self._inn_ok(e) or e.text.strip() in confirmed]

        # номер, опознанный по якорному слову где угодно в тексте, скрывается везде
        candidates += self._person_token_repeats(text, candidates)

        anchored = {e.text.strip() for e in candidates if e.source == "docref"}
        anchored |= {e.text.strip() for e in candidates
                     if e.type in ("INN", "KPP") and e.source == "requisite"}
        
        if anchored:
            extra = [Entity(e.type, e.text, e.start, e.end, e.key, source="repeat")
                     for e in self._repeats(text, anchored, candidates)]
            candidates += extra

        # Дата рядом с номером документа - строго после повторов
        dates = self._dates_after_docrefs(text, candidates)
        if dates:
            candidates += dates
            candidates += [Entity(e.type, e.text, e.start, e.end, e.key, source="repeat")
                           for e in self._repeats(
                               text, {e.text.strip() for e in dates}, candidates)]

        candidates += self._org_case_repeats(text, candidates)
        candidates = self._without_geo_persons(candidates)

        # слово из подтвержденного названия, оставшееся открытым в другом месте.
        candidates += self._org_token_repeats(text, candidates)

        # второе имя в скобках
        aliases = self._bracket_aliases(text, candidates)
        if aliases:
            candidates += aliases
            candidates += self._org_token_repeats(text, candidates + aliases)

        # идемпотентность для стоящих меток и спанов внутри них
        occupied = [(m.start(), m.end()) for m in LABEL_RE.finditer(text)]
        accepted = self._resolve(candidates, occupied)

        replacements: list[tuple[int, int, str]] = []
        for ent in sorted(accepted, key=lambda e: e.start):
            placeholder = self._assign_label(labels, ent)
            replacements.append((ent.start, ent.end, placeholder))

        out, pos = [], 0
        for start, end, placeholder in replacements:
            out.append(source[pos:start])
            out.append(placeholder)
            pos = end
        out.append(source[pos:])
        return "".join(out), mapping

    @staticmethod
    def _resolve(candidates: list[Entity], occupied: list[tuple[int, int]]) -> list[Entity]:
        taken = list(occupied)
        accepted = []
        # Словарные сущности важнее любого типа: их задал пользователь, а NER может
        # ошибиться (например, принять словарное ORG "Ромашка Россия" за PERSON).

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
        # лемму подставляем только для явно косвенной формы
        if ent.type == "PERSON" and ent.oblique:
            original = ent.key.title()  # восстанавливается именительный падеж
        labels[placeholder] = {"type": ent.type, "original": original, "key": ent.key, "n": n}
        return placeholder

    @staticmethod
    def _is_own_artifact(s: str) -> bool:
        from ..detection.recognizers import FAKE_EMAIL_RE

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
        # mask + второй проход локальной LLM по уже замаскированному тексту.
        from ..detection.auditor import audit, ollama_alive

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
