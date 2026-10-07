"""Имена и организации через Natasha"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from ..recognizers.recognizers import Entity
from . import helpers

if TYPE_CHECKING:
    from natasha.morph.vocab import MorphForm


def _role_tail_len(text: str) -> int:
    # длина хвоста-должности в конце спана
    m = helpers.ROLE_TAIL.search(text)
    return len(m.group()) if m else 0


def _is_stop_term(text: str) -> bool:
    # родовой термин
    term = " ".join(text.lower().split()).strip(" -–,.:;()[]\"'«»")
    if not term:
        return True
    if term in helpers.STOP_TERMS:
        return True
    head = helpers.TERM_TAIL.sub("", term).strip()
    return bool(head) and head != term and head in helpers.STOP_TERMS


def _demarkup(text: str) -> str:
    # теневая копия текста без разметки
    text = helpers.MD_LINE_EDGE.sub(lambda m: " " * len(m.group()), text)
    return helpers.MD_INLINE.sub(" ", text)


def _detitle_caps(text: str) -> str:
    return helpers.CAPS_RUN.sub(lambda m: m.group().capitalize(), text)


def _terminate_lines(text: str) -> str:
    # завершить точкой строки без знака препинания на конце
    return helpers.LINE_BREAK.sub(".", text)


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

    def _parse(self, word: str) -> list[MorphForm]:
        # MorphVocab всегда отдает MorphForm, но pymorphy2 без аннотаций и Pylance видит tuple
        return cast("list[MorphForm]", self._morph_vocab.parse(word))

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
        parses = [p for p in self._parse(word.capitalize()) if p.is_known]
        return bool(parses) and all("Geox" in p.tag.grammemes for p in parses)

    def known_common_word(self, word: str) -> bool:
        parses = [p for p in self._parse(word.capitalize()) if p.is_known]
        if not parses:
            return False
        ok = helpers.NAME_GRAMMEMES | {"Orgn"}
        return not any(g in ok for p in parses for g in p.tag.grammemes)

    def _has_patronymic(self, span: str) -> bool:
        for word in re.findall(r"[А-ЯЁа-яё]+", span):
            if any("Patr" in p.tag.grammemes for p in self._parse(word)):
                return True
        return False

    def _looks_like_surname(self, word: str) -> bool:
        if word.lower() in helpers.STOP_TERMS:
            return False
        parses = self._parse(word)
        if any(g in helpers.NAME_GRAMMEMES for p in parses for g in p.tag.grammemes):
            return True
        return not any(p.is_known for p in parses)

    def _name_words(self, text: str) -> list[Entity]:
        # Одинокое слово капсом, которое словарь знает как имя или фамилию.

        out = []
        for m in re.finditer(r"(?<![А-ЯЁ\w])[А-ЯЁ]{4,}(?![А-ЯЁ\w])", text):
            parses = self._parse(m.group().capitalize())
            known = [p for p in parses if p.is_known]
            if known and any(g in helpers.NAME_GRAMMEMES for g in known[0].tag.grammemes):
                out.append(
                    Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower())
                )
        return out

    def _is_junk_span(self, ent: Entity) -> bool:
        if helpers.DUTY_HEAD.match(ent.text.strip()):
            return True

        first = re.match(r"[А-ЯЁA-Za-zа-яё]+", ent.text.strip())
        if first:
            parses = [p for p in self._parse(first.group().lower())
                      if p.is_known]
            if parses and all(p.tag.POS in {"VERB", "INFN"} for p in parses):
                return True
        if helpers.JUNK_INSIDE.search(ent.text):
            return True
        # Слово капсом, которые словарь знает обычными словами:
        # заголовки резюме - "РЕШЕНИЕ", "ОТКЛОНЕНА", "ПРОЕКТОВ". Незнакомое
        # словарю слово капсом не трогаем - это может быть аббревиатура-название.
        words = re.findall(r"[А-ЯЁ]{2,}", ent.text)
        if words and words == re.findall(r"[А-ЯЁа-яёA-Za-z]+", ent.text):
            known_common = []
            for word in words:
                parses = [p for p in self._parse(word.capitalize())
                          if p.is_known]
                # Orgn - пометка словаря "название организации": так размечены названия, давно вошедшие в словарь
                ok = helpers.NAME_GRAMMEMES | {"Orgn"}
                known_common.append(bool(parses) and not any(
                    g in ok for p in parses for g in p.tag.grammemes))
            if all(known_common):
                return True
        return False

    @staticmethod
    def _in_stack_line(text: str, ent: Entity) -> bool:
        start = text.rfind("\n", 0, ent.start) + 1
        return bool(helpers.STACK_LINE.match(text, start))

    def _plausible(self, ent: Entity) -> bool:
        if self._is_junk_span(ent):
            return False
        # проверка на географическое название
        if ent.type == "PERSON" and " " not in ent.text.strip():
            parses = [p for p in self._parse(ent.text.strip().capitalize())
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
                parses = self._parse(ent.text)
                if any(p.is_known for p in parses):
                    return any(g in helpers.NAME_GRAMMEMES for p in parses for g in p.tag.grammemes)
            elif not self._looks_like_fio(tokens):
                return False
        return True

    def looks_like_person(self, text: str) -> bool:
        # похож ли спан на ФИО живого человека, а не на марку товара
        for token in text.split():
            known = [p for p in self._parse(token) if p.is_known]
            if any(g in helpers.NAME_GRAMMEMES for p in known for g in p.tag.grammemes):
                return True
        return False

    def _looks_like_fio(self, tokens: list[str]) -> bool:
        # похож ли многословный спан на ФИО, а не на название товара
        known_common = False
        for token in tokens:
            known = [p for p in self._parse(token) if p.is_known]
            if any(g in helpers.NAME_GRAMMEMES for p in known for g in p.tag.grammemes):
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
        for span in doc.spans or []:
            etype = helpers.TYPE_MAP.get(span.type)
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
                for t in doc.tokens or []
                if span.start <= t.start < stop
            ]
            oblique = bool(cases) and "Nom" not in cases
            # текст берется из ориганала
            raw = text[span.start:stop]
            out.append(
                Entity(etype, raw, span.start, stop, key, oblique)
            )
        return out
