"""Имена и организации через Natasha"""
from __future__ import annotations

import re

from ..recognizers.entity import Entity
from . import helpers, morph


def _role_tail_len(text: str) -> int:
    # длина хвоста-должности в конце спана
    m = helpers.ROLE_TAIL.search(text)
    return len(m.group()) if m else 0


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
        from natasha import Doc, NewsEmbedding, NewsMorphTagger, NewsNERTagger, Segmenter

        self._Doc = Doc
        self._segmenter = Segmenter()
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

    @staticmethod
    def _has_patronymic(span: str) -> bool:
        return any("Patr" in p.tag.grammemes
                   for word in re.findall(r"[А-ЯЁа-яё]+", span) for p in morph.parse(word))

    @staticmethod
    def _looks_like_surname(word: str) -> bool:
        if word.lower() in helpers.STOP_TERMS:
            return False
        parses = morph.parse(word)
        return morph.has_name(parses) or not any(p.is_known for p in parses)

    @staticmethod
    def _name_words(text: str) -> list[Entity]:
        # Одинокое слово капсом, которое словарь знает как имя или фамилию.
        out = []
        for m in re.finditer(r"(?<![А-ЯЁ\w])[А-ЯЁ]{4,}(?![А-ЯЁ\w])", text):
            if morph.has_name(morph.known(m.group().capitalize())[:1]):
                out.append(Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower()))
        return out

    @staticmethod
    def _is_junk_span(ent: Entity) -> bool:
        if helpers.DUTY_HEAD.match(ent.text.strip()):
            return True

        first = re.match(r"[А-ЯЁA-Za-zа-яё]+", ent.text.strip())
        if first:
            parses = morph.known(first.group().lower())
            if parses and all(p.tag.POS in {"VERB", "INFN"} for p in parses):
                return True
        if helpers.JUNK_INSIDE.search(ent.text):
            return True
        # Слово капсом, которые словарь знает обычными словами:
        # заголовки резюме - "РЕШЕНИЕ", "ОТКЛОНЕНА", "ПРОЕКТОВ". Незнакомое
        # словарю слово капсом не трогаем - это может быть аббревиатура-название.
        words = re.findall(r"[А-ЯЁ]{2,}", ent.text)
        return (bool(words) and words == re.findall(r"[А-ЯЁа-яёA-Za-z]+", ent.text)
                and all(morph.is_known_common(w) for w in words))

    @staticmethod
    def _in_stack_line(text: str, ent: Entity) -> bool:
        start = text.rfind("\n", 0, ent.start) + 1
        return bool(helpers.STACK_LINE.match(text, start))

    def _plausible(self, ent: Entity) -> bool:
        if self._is_junk_span(ent):
            return False
        if ent.type == "PERSON" and " " not in ent.text.strip() and morph.is_geography(ent.text.strip()):
            return False

        # отсев заведомого мусора NER на верстке резюме и выгрузок
        if "\n" in ent.text:
            return False
        if morph.is_stop_term(ent.text):
            return False
        if ent.type == "PERSON":
            tokens = ent.text.split()
            if len(tokens) == 1:
                parses = morph.parse(ent.text)
                if any(p.is_known for p in parses):
                    return morph.has_name(parses)
            elif not self._looks_like_fio(tokens):
                return False
        return True

    @staticmethod
    def _looks_like_fio(tokens: list[str]) -> bool:
        # похож ли многословный спан на ФИО, а не на название товара
        known_common = False
        for token in tokens:
            known = morph.known(token)
            if morph.has_name(known):
                return True
            known_common = known_common or bool(known)
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
                span.normalize(morph.vocab())
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
