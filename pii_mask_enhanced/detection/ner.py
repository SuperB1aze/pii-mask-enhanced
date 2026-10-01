"""Имена и организации через Natasha"""
from __future__ import annotations

import re

from .recognizers import Entity

_TYPE_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}

# Граммемы личного имени в pymorphy: имя, фамилия, отчество.
_NAME_GRAMMEMES = {"Name", "Surn", "Patr"}

# Термины, которые NER регулярно принимает за организацию или персону в резюме, вакансиях и служебной верстке.
STOP_TERMS = frozenset({
    "dwh", "data mart", "etl", "bi", "brd", "fsd", "lm", "sql", "ms sql",
    "powerbi", "power bi", "crm", "erp", "kpi", "api", "ui", "ux",
    "ml", "nlp", "ner", "llm", "genai", "rag", "mcp", "sdd", "ci/cd", "devops",
    "backend", "frontend", "fullstack", "qa", "ux/ui",
    "jira", "redmine", "confluence", "ms project", "mysql", "postgresql",
    "postgres", "mongodb", "clickhouse", "redis", "docker", "kubernetes",
    "laravel", "django", "react", "vue", "git", "gitlab", "github",
    "ollama", "claude", "claude api", "claude code", "openai api", "cursor",
    "langchain", "excel", "ms office", "figma", "notion", "trello", "asana",
    "hrbp", "t&d", "talent review", "performance review", "performance",
    "ispring", "power point", "powerpoint", "smart", "9-box", "ии", "ис",
    "obsidian", "sqlite", "onnx", "codex", "qwen", "ktalk", "linkedin", "vk",
    "google", "telegram", "whisper", "pert", "wbs", "субд", "cv", "pdf",
    "scrum", "kanban", "waterfall", "agile", "safe", "evm", "pmbok", "itil",
    "spec-driven development", "time & material", "fixed price",
    "product owner", "product manager", "project manager", "team lead",
    "tech lead", "delivery", "delivery/pm", "pm", "рп", "тимлид", "cto", "cio",
    "scrum master", "бизнес-аналитик", "системный аналитик",
    "ai", "it", "hr", "ib", "иб", "ит", "nda", "p&l", "roi", "tco", "sla",
    "ткп", "тз", "нда", "гост", "ндс", "ооо", "ано", "ип",
    "инн", "кпп", "огрн", "огрнип", "окпо", "октмо", "оквэд", "бик",
    "снилс", "кбк", "уин","тмц", "пто", "егрюл", "егрип", "ндфл", "фсс", "пфр", "омс", "усн",
    "осно", "envd", "енвд", "кудир", "тк рф", "гк рф", "жкх", "смр", "окс",
    "кс-2", "кс-3", "тору", "зуп", "мсфо", "рсбу", "авр", "первичка",
    "саше","специализации", "специализация", "занятость", "планирование",
    "анализ данных", "навыки", "образование", "опыт работы", "транскрипт",
    "ключевые навыки", "о себе", "достижения", "проекты", "портфолио",
})

# компания, чье название начинается со стоп-термина ("AI-Systems"), перестаёт маскироваться
_TERM_TAIL = re.compile(r"[-/].*$")

# должность за названием работодателя ("Северная Торговая Компания - логист")
_ROLE_TAIL = re.compile(r"\s+[-–—]\s+[а-яёa-z][^\n]*\Z")


def _role_tail_len(text: str) -> int:
    # длина хвоста-должности в конце спана
    m = _ROLE_TAIL.search(text)
    return len(m.group()) if m else 0


# фикс разметки, которая сбивает сегментацию slovnet
_MD_LINE_EDGE = re.compile(r"^[ \t]*[#+|]+[ \t]*|[ \t]*[#|]+[ \t]*$", re.M)
_MD_INLINE = re.compile(r"[|`]")
# перевод строки после строки, не оканчивающейся знаком препинания
_LINE_BREAK = re.compile(r"(?<=[^\s.!?:;,\-|>])\n")


def _is_stop_term(text: str) -> bool:
    # родовой термин
    term = " ".join(text.lower().split()).strip(" -–,.:;()[]\"'«»")
    if not term:
        return True
    if term in STOP_TERMS:
        return True
    head = _TERM_TAIL.sub("", term).strip()
    return bool(head) and head != term and head in STOP_TERMS


def _demarkup(text: str) -> str:
    # теневая копия текста без разметки
    text = _MD_LINE_EDGE.sub(lambda m: " " * len(m.group()), text)
    return _MD_INLINE.sub(" ", text)


_CAPS_RUN = re.compile(r"[А-ЯЁA-Z]{2,}(?:[-'][А-ЯЁA-Z]{2,})*")


def _detitle_caps(text: str) -> str:
    return _CAPS_RUN.sub(lambda m: m.group().capitalize(), text)


def _terminate_lines(text: str) -> str:
    # завершить точкой строки без знака препинания на конце
    return _LINE_BREAK.sub(".", text)


class NatashaNer:
    _shared = None

    def __init__(self) -> None:
        from natasha import (
            Doc,
            MorphVocab,
            NewsEmbedding,
            NewsMorphTagger,
            NewsNERTagger,
            Segmenter,
        )

        self._Doc = Doc
        self._segmenter = Segmenter()
        self._morph_vocab = MorphVocab()
        emb = NewsEmbedding()
        self._morph_tagger = NewsMorphTagger(emb)
        self._ner_tagger = NewsNERTagger(emb)

    @classmethod
    def shared(cls) -> "NatashaNer":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def extract(self, text: str) -> list[Entity]:
        # два прохода по одному тексту, объединение находок.
        shadow = _demarkup(text)
        found = (
            self._tag(text, shadow)
            + self._tag(text, _terminate_lines(shadow))
            + self._tag(text, _terminate_lines(_detitle_caps(shadow)))
            + self._name_words(text)
        )
        seen, out = set(), []
        for ent in found:
            key = (ent.type, ent.start, ent.end)
            if key in seen or not self._plausible(ent):
                continue
            if ent.type == "ORG" and self._in_stack_line(text, ent):
                continue
            seen.add(key)
            out.append(ent)
        out += self._surname_by_patronymic(text, out)
        return out

    # cлово с большой буквы вплотную к спану: слева "Сухарева Алина", справа "Алина Сухарева"
    _LEFT_WORD = re.compile(r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)[ \t]+$")
    _RIGHT_WORD = re.compile(r"^[ \t]+([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)")

    def _surname_by_patronymic(self, text: str, found: list[Entity]) -> list[Entity]:
        # дотянуть спан ФИО до соседней фамилии, когда в нем есть отчество.
        out = []
        for ent in found:
            if ent.type != "PERSON" or not self._has_patronymic(ent.text):
                continue
            left = self._LEFT_WORD.search(text[:ent.start])
            if left and self._looks_like_surname(left.group(1)):
                out.append(Entity("PERSON", text[left.start(1):ent.end],
                                  left.start(1), ent.end,
                                  text[left.start(1):ent.end].lower()))
                continue
            right = self._RIGHT_WORD.match(text[ent.end:])
            if right and self._looks_like_surname(right.group(1)):
                end = ent.end + right.end(1)
                out.append(Entity("PERSON", text[ent.start:end],
                                  ent.start, end, text[ent.start:end].lower()))
        return out

    def is_geography(self, word: str) -> bool:
        parses = [p for p in self._morph_vocab.parse(word.capitalize()) if p.is_known]
        return bool(parses) and all("Geox" in p.tag.grammemes for p in parses)

    def known_common_word(self, word: str) -> bool:
        parses = [p for p in self._morph_vocab.parse(word.capitalize()) if p.is_known]
        if not parses:
            return False
        ok = _NAME_GRAMMEMES | {"Orgn"}
        return not any(g in ok for p in parses for g in p.tag.grammemes)

    def _has_patronymic(self, span: str) -> bool:
        for word in re.findall(r"[А-ЯЁа-яё]+", span):
            if any("Patr" in p.tag.grammemes for p in self._morph_vocab.parse(word)):
                return True
        return False

    def _looks_like_surname(self, word: str) -> bool:
        if word.lower() in STOP_TERMS:
            return False
        parses = self._morph_vocab.parse(word)
        if any(g in _NAME_GRAMMEMES for p in parses for g in p.tag.grammemes):
            return True
        return not any(p.is_known for p in parses)

    def _name_words(self, text: str) -> list[Entity]:
        # Одинокое слово капсом, которое словарь знает как имя или фамилию.

        out = []
        for m in re.finditer(r"(?<![А-ЯЁ\w])[А-ЯЁ]{4,}(?![А-ЯЁ\w])", text):
            parses = self._morph_vocab.parse(m.group().capitalize())
            known = [p for p in parses if p.is_known]
            if known and any(g in _NAME_GRAMMEMES for g in known[0].tag.grammemes):
                out.append(
                    Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower())
                )
        return out

    # кусок названия
    _JUNK_INSIDE = re.compile(r"[+*/\\|]|\*\*")

    # спан, начинающийся с отглагольного существительного
    _DUTY_HEAD = re.compile(
        r"^(?:полн\w+\s+)?(?:организация|ведение|проведение|подготовка|заключение"
        r"|обучение|консультирование|проверка|контроль|составление|оформление"
        r"|сопровождение|формирование|планирование|управление|взаимодействие"
        r"|обеспечение|разработка|внедрение|сдача|прием|учет|анализ)\b",
        re.IGNORECASE)

    def _is_junk_span(self, ent: Entity) -> bool:
        if self._DUTY_HEAD.match(ent.text.strip()):
            return True

        first = re.match(r"[А-ЯЁA-Za-zа-яё]+", ent.text.strip())
        if first:
            parses = [p for p in self._morph_vocab.parse(first.group().lower())
                      if p.is_known]
            if parses and all(p.tag.POS in {"VERB", "INFN"} for p in parses):
                return True
        if self._JUNK_INSIDE.search(ent.text):
            return True
        # Слово капсом, которые словарь знает обычными словами:
        # заголовки резюме - "РЕШЕНИЕ", "ОТКЛОНЕНА", "ПРОЕКТОВ". Незнакомое
        # словарю слово капсом не трогаем - это может быть аббревиатура-название.
        words = re.findall(r"[А-ЯЁ]{2,}", ent.text)
        if words and words == re.findall(r"[А-ЯЁа-яёA-Za-z]+", ent.text):
            known_common = []
            for word in words:
                parses = [p for p in self._morph_vocab.parse(word.capitalize())
                          if p.is_known]
                # Orgn - пометка словаря "название организации": так размечены названия, давно вошедшие в словарь
                ok = _NAME_GRAMMEMES | {"Orgn"}
                known_common.append(bool(parses) and not any(
                    g in ok for p in parses for g in p.tag.grammemes))
            if all(known_common):
                return True
        return False

    # строка перечня инструментов
    _STACK_LINE = re.compile(
        r"[ \t>*-]*(?:стек|навыки|инструменты|технологии|hard skills|tech stack"
        r"|владею|знание инструментов|дополнительно|языки и библиотеки"
        r"|базы данных|бд|аналитика|визуализация)[^:\n]{0,60}[:：]", re.IGNORECASE)

    def _in_stack_line(self, text: str, ent: Entity) -> bool:
        start = text.rfind("\n", 0, ent.start) + 1
        return bool(self._STACK_LINE.match(text, start))

    def _plausible(self, ent: Entity) -> bool:
        if self._is_junk_span(ent):
            return False
        # проверка на географическое название
        if ent.type == "PERSON" and " " not in ent.text.strip():
            parses = [p for p in self._morph_vocab.parse(ent.text.strip().capitalize())
                      if p.is_known]
            if parses and all("Geox" in p.tag.grammemes for p in parses):
                return False

        # отсев заведомого мусора NER на верстке резюме и выгрузок
        if "\n" in ent.text:
            return False
        if _is_stop_term(ent.text):
            return False
        if ent.type == "PERSON":
            tokens = ent.text.split()
            if len(tokens) == 1:
                parses = self._morph_vocab.parse(ent.text)
                if any(p.is_known for p in parses):
                    return any(g in _NAME_GRAMMEMES for p in parses for g in p.tag.grammemes)
            elif not self._looks_like_fio(tokens):
                return False
        return True

    def looks_like_person(self, text: str) -> bool:
        # похож ли спан на ФИО живого человека, а не на марку товара
        for token in text.split():
            known = [p for p in self._morph_vocab.parse(token) if p.is_known]
            if any(g in _NAME_GRAMMEMES for p in known for g in p.tag.grammemes):
                return True
        return False

    def _looks_like_fio(self, tokens: list[str]) -> bool:
        # похож ли многословный спан на ФИО, а не на название товара
        known_common = False
        for token in tokens:
            known = [p for p in self._morph_vocab.parse(token) if p.is_known]
            if any(g in _NAME_GRAMMEMES for p in known for g in p.tag.grammemes):
                return True
            if known:
                known_common = True
        return not known_common

    def _tag(self, text: str, shadow: str) -> list[Entity]:
        doc = self._Doc(shadow)
        doc.segment(self._segmenter)
        doc.tag_morph(self._morph_tagger)
        doc.tag_ner(self._ner_tagger)
        out = []
        for span in doc.spans:
            etype = _TYPE_MAP.get(span.type)
            if etype is None:
                continue
            try:
                span.normalize(self._morph_vocab)
                key = (span.normal or span.text).lower()
            except Exception:
                key = span.text.lower()
            # косвенный падеж - если ни один токен спана не в именительном
            stop = span.stop - _role_tail_len(text[span.start:span.stop])
            if stop <= span.start:
                continue
            if stop != span.stop:
                # обрезка хвоста
                key = text[span.start:stop].lower()
            cases = [
                (t.feats or {}).get("Case")
                for t in doc.tokens
                if span.start <= t.start < stop
            ]
            oblique = bool(cases) and "Nom" not in cases
            # текст берется из ориганала
            raw = text[span.start:stop]
            out.append(
                Entity(etype, raw, span.start, stop, key, oblique)
            )
        return out
