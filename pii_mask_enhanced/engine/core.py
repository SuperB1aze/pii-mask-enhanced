"""Ядро: mask/unmask со stateless mapping.

Принципы:
- распознаватели только находят сущности, замену делает детерминированный код;
- одинаковая сущность (включая словоформы) -> одна метка на весь диалог;
- mapping возвращается вызывающему, сервис ничего не хранит;
- метка, которой не было во входе, при unmask превращается в UNKNOWN - защита
  от выдуманных моделью данных.

Устройство: Masker собирает кандидатов (распознаватели, NER, аудитор), расширяет их
повторами (propagation), решает пересечения (_resolve) и выдает метки (labels).
"""
from __future__ import annotations

import copy
import re

from ..detection.ner import morph
from ..detection.ner.ner import NatashaNer
from ..detection.recognizers.entity import Entity
from ..detection.recognizers.finders.spans import overlaps
from ..detection.recognizers.recognizers import find_format_entities
from ..detection.recognizers.regulars import ORG_FORM_RE
from ..detection.registry import sources
from ..detection.registry.entity_types import DEFAULT_TYPES, PRIORITY, SPREAD_TYPES, check_types
from . import labels as lbl
from . import propagation as prop
from .labels import LABEL_RE, UNKNOWN  # noqa: F401  (UNKNOWN - часть API модуля)

# Типографские близнецы дефиса и пробела ломают токенизацию: неразрывный дефис
# U+2011 превращает составное название в мусор, и распознаватель не видит ни
# организацию, ни стоящую рядом фамилию.
# По этой причине нормализуем только текст, по которому мы ищем ПД

_TYPO_TWINS = {"‐": "-", "‑": "-", "‒": "-", "−": "-",
               " ": " ", " ": " ", " ": " "}
_TYPO_RE = re.compile("[" + "".join(_TYPO_TWINS) + "]")


def normalize_for_analysis(text: str) -> str:
    """Свести типографские близнецы к простым символам, не меняя длину."""
    return _TYPO_RE.sub(lambda m: _TYPO_TWINS[m.group()], text)


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
        check_types(types)
        check_types(ner_types or ())
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
        # типы, которые принимаем от NER
        self._ner_allowed = self.types if self.ner_types is None else self.types & self.ner_types
        self._use_ner = ner and bool({"PERSON", "ORG", "LOC"} & self._ner_allowed)
        # названия организаций, заданные снаружи (см. recognizers.load_org_dict)
        self.org_names = tuple(org_names)

    # --- фильтры кандидатов ---

    def _ner_org_ok(self, ent: Entity) -> bool:
        # Организация от NER: с правовой формой или без разницы. Правило касается ТОЛЬКО организаций и только тех, что предложил NER.
        if ent.type == "ORG" and self.ner_org_needs_form:
            return bool(ORG_FORM_RE.search(ent.text))
        if ent.type == "PERSON" and self.ner_person_needs_fio:
            if self._supported(ent):
                return True
            return morph.looks_like_person(ent.text)
        return True

    def _inn_ok(self, ent: Entity) -> bool:
        """ИНН без подписи в строгом режиме не принимается (см. inn_needs_label)."""
        if not self.inn_needs_label or ent.type != "INN":
            return True
        return ent.source != sources.BARE or ent.text.strip() in self.trusted_numbers

    def with_hints(self, supported_names: frozenset[str], trusted_numbers: frozenset[str]) -> Masker:
        """Копия с подсказками документа для строгого режима; заданные явно не заменяются."""
        clone = copy.copy(self)
        if self.ner_person_needs_fio and not self.supported_names:
            clone.supported_names = supported_names
        if self.inn_needs_label and not self.trusted_numbers:
            clone.trusted_numbers = trusted_numbers
        return clone

    def _supported(self, ent: Entity) -> bool:
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

        # Ищем по нормализованному тексту, отдаем исходный (см. _TYPO_TWINS).
        source = text
        text = normalize_for_analysis(text)

        candidates = self._collect(text, extra_entities)
        candidates = self._propagate(text, candidates)

        # идемпотентность для стоящих меток и спанов внутри них
        occupied = [(m.start(), m.end()) for m in LABEL_RE.finditer(text)]
        accepted = self._resolve(candidates, occupied)
        return self._render(source, accepted, mapping["labels"]), mapping

    def _collect(self, text: str, extra_entities: list[Entity] | None) -> list[Entity]:
        # Первичные находки: форматные распознаватели, NER, аудитор.
        candidates = [
            e for e in find_format_entities(text, self.org_names) if e.type in self.types
        ]
        if self._use_ner:
            candidates += [e for e in NatashaNer.shared().extract(text)
                           if e.type in self._ner_allowed and self._ner_org_ok(e)]
        if extra_entities:
            candidates += [e for e in extra_entities if not lbl.is_own_artifact(e.text)]

        # номер, подписанный реквизитом где угодно в тексте, считается реквизитом везде
        if self.inn_needs_label:
            confirmed = {e.text.strip() for e in candidates
                         if e.type == "INN" and e.source == sources.REQUISITE}
            candidates = [e for e in candidates
                          if self._inn_ok(e) or e.text.strip() in confirmed]
        return candidates

    def _propagate(self, text: str, candidates: list[Entity]) -> list[Entity]:
        # Повторы и производные найденного. Порядок шагов важен: каждый следующий
        # видит находки предыдущих.
        if "PERSON" in self.types:
            candidates += prop.person_token_repeats(text, candidates)

        # номер, опознанный по якорному слову где угодно в тексте, скрывается везде
        anchored = {e.text.strip() for e in candidates if e.source == sources.DOCREF}
        anchored |= {e.text.strip() for e in candidates
                     if e.type in SPREAD_TYPES and e.source == sources.REQUISITE}
        if anchored:
            candidates += prop.repeats(text, anchored, candidates)

        # Дата рядом с номером документа - строго после повторов
        if "DATE" in self.types:
            dates = prop.dates_after_docrefs(text, candidates)
            if dates:
                candidates += dates
                candidates += prop.repeats(text, {e.text.strip() for e in dates}, candidates)

        candidates += prop.org_case_repeats(text, candidates)

        if not self._use_ner:
            # без NER подтвержденные названия приходят из словаря и по правовой форме,
            # проверка по словарю общих слов недоступна
            return candidates + prop.bracket_aliases(text, candidates)

        candidates = prop.without_geo_persons(candidates)
        # слово из подтвержденного названия, оставшееся открытым в другом месте
        candidates += prop.org_token_repeats(text, candidates)
        # второе имя в скобках и его повторы
        aliases = prop.bracket_aliases(text, candidates)
        if aliases:
            candidates += aliases
            candidates += prop.org_token_repeats(text, candidates)
        return candidates

    @staticmethod
    def _resolve(candidates: list[Entity], occupied: list[tuple[int, int]]) -> list[Entity]:
        taken = list(occupied)
        accepted = []
        # Словарные сущности важнее любого типа: их задал пользователь, а NER может
        # ошибиться (например, принять словарное ORG "Ромашка Россия" за PERSON).

        ordered = sorted(
            candidates,
            key=lambda e: (
                0 if e.source == sources.DICT else 1,
                PRIORITY[e.type],
                -(e.end - e.start),
                e.start,
            ),
        )
        for ent in ordered:
            span = (ent.start, ent.end)
            if any(overlaps(span, t) for t in taken):
                continue
            taken.append(span)
            accepted.append(ent)
        return accepted

    @staticmethod
    def _render(source: str, accepted: list[Entity], labels: dict) -> str:
        # Метки выдаются слева направо: номер N отражает порядок появления в тексте.
        out, pos = [], 0
        for ent in sorted(accepted, key=lambda e: e.start):
            out.append(source[pos:ent.start])
            out.append(lbl.assign_label(labels, ent))
            pos = ent.end
        out.append(source[pos:])
        return "".join(out)

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

    # --- unmask ---

    def unmask(self, text: str, mapping: dict) -> str:
        return lbl.unmask(text, mapping)
