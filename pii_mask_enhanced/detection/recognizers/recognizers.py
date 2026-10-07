"""Форматные ПД РФ: regex + контрольные суммы."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import helpers
from . import regulars as regs
from .validators import Validator

@dataclass
class Entity:
    type: str
    text: str
    start: int
    end: int
    key: str  # ключ консистентности: одинаковый key -> одна метка
    # слово не в именительном падеже ("Ивану")
    oblique: bool = False
    # "dict", "requisite", "bare" и др. - кто нашел; решает спор при пересечениях
    source: str = ""


def _prefixes(words, minlen: int = 6) -> dict[str, str]:
    """Обрезки слов -> полное слово: PDF режет текст по колонке ("КОНСТАНТИНОВИ")."""
    out: dict[str, str] = {}
    for w in words:
        for n in range(minlen, len(w)):
            out.setdefault(w[:n], w)
    return out


def _org_stems(name: str) -> list[str]:
    """Отличительные слова названия."""
    words = re.findall(r"[А-ЯЁA-Z][\w-]{2,}", name)
    return [w for w in words if w.lower() not in helpers.ORG_GENERIC]


def _url_host(url: str) -> str:
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0]
    return host.lower().removeprefix("www.")


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def find_format_entities(text: str, org_names: tuple[str, ...] = ()) -> list[Entity]:
    """Найти форматные ПД. org_names - словарь организаций (load_org_dict)."""
    out: list[Entity] = []

    for m in regs.PROFILE_NICK_RE.finditer(text):
        out.append(Entity("TG", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="profile"))

    for m in regs.BIRTH_DATE_RE.finditer(text):
        out.append(Entity("DATE", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="birth"))

    for m in regs.RESIDENCE_RE.finditer(text):
        out.append(Entity("ADDRESS", m.group(1), m.start(1), m.end(1),
                          m.group(1).lower(), source="residence"))

    for m in regs.EMAIL_RE.finditer(text):
        if not regs.FAKE_EMAIL_RE.match(m.group()):
            out.append(Entity("EMAIL", m.group(), m.start(), m.end(), m.group().lower()))

    for m in regs.TG_RE.finditer(text):
        out.append(Entity("TG", m.group(), m.start(), m.end(), m.group().lower()))

    for rx in (regs.URL_SCHEME_RE, regs.BARE_DOMAIN_RE):
        for m in rx.finditer(text):
            url = m.group().rstrip(".,;:!?")
            if _url_host(url) in helpers.STOP_HOSTS:
                continue
            out.append(Entity("URL", url, m.start(), m.start() + len(url), url.lower()))

    for m in regs.PHONE_RE.finditer(text):
        d = digits(m.group())
        if d[1:4] != regs.FAKE_PHONE_CODE:
            out.append(Entity("PHONE", m.group(), m.start(), m.end(), d))

    for m in regs.CARD_RE.finditer(text):
        d = digits(m.group())
        if len(d) == 16 and Validator.luhn_ok(d):
            out.append(Entity("CARD", m.group(), m.start(), m.end(), d))

    for m in regs.SNILS_RE.finditer(text):
        d = digits(m.group())
        if Validator.snils_ok(d):
            out.append(Entity("SNILS", m.group(), m.start(), m.end(), d))

    for m in regs.INN_RE.finditer(text):
        d = m.group()
        if Validator.inn_ok(d):
            # без подписи "ИНН" - строгий режим ядра это учитывает
            out.append(Entity("INN", d, m.start(), m.end(), d, source="bare"))

    for m in regs.CERT_RE.finditer(text):
        v = m.group()
        if not (any(c.isdigit() for c in v) and any(c.isalpha() for c in v)):
            continue
        out.append(Entity("CERT", v, m.start(), m.end(), v.lower()))

    for m in regs.DOCREF_RE.finditer(text):
        num = m.group(2)
        if not any(ch.isdigit() for ch in num):
            continue
        # без "№" голое число - скорее сумма
        if not m.group(1) and num.isdigit():
            continue
        out.append(Entity("DOCREF", num, m.start(2), m.end(2), num.lower(),
                          source="docref"))
        if m.group(3):
            out.append(Entity("DATE", m.group(3), m.start(3), m.end(3),
                              m.group(3), source="docref"))

    for m in regs.PAIRED_REQUISITE_RE.finditer(text):
        labels = helpers.SPLIT_LABELS.split(m.group(1))
        nums = helpers.SPLIT_NUMS.split(m.group(2))
        if len(labels) != len(nums):
            # не угадываем, где ИНН, а где КПП
            continue
        pos = m.start(2)
        for label, num in zip(labels, nums):
            if not num:
                continue        # у ИП нет КПП
            start = text.index(num, pos)
            etype = helpers.REQ_TYPE.get(label.strip().lower(), "REQ")
            out.append(Entity(etype, num, start, start + len(num), num,
                              source="requisite"))
            pos = start + len(num)

    for m in regs.REQUISITE_RE.finditer(text):
        num = m.group(2)
        etype = helpers.REQ_TYPE.get(m.group(1).lower(), "REQ")
        out.append(Entity(etype, num, m.start(2), m.end(2), num, source="requisite"))

    for m in regs.ACCOUNT_RE.finditer(text):
        num = m.group(2)
        out.append(Entity("ACCOUNT", num, m.start(2), m.end(2), num, source="requisite"))

    # оставляем самую полную находку адреса
    addrs = [(m.start(), m.end(), m.group())
             for rx in (regs.ADDRESS_RE, regs.ADDRESS_TAIL_RE, regs.ADDRESS_RUN_RE, regs.ADDRESS_INDEX_RE)
             for m in rx.finditer(text)]
    for start, end, txt in addrs:
        if any(a <= start and end <= b and (a, b) != (start, end) for a, b, _ in addrs):
            continue
        out.append(Entity("ADDRESS", txt, start, end, " ".join(txt.lower().split())))

    for rx in regs.DOC_REQUISITE_RES:
        for m in rx.finditer(text):
            for g in range(1, (m.lastindex or 0) + 1):
                if m.group(g):
                    out.append(Entity("REQ", m.group(g), m.start(g), m.end(g), m.group(g)))

    # Слова названий (stems) ищем по документу только от регулярок: ошибку NER
    # это размножило бы по всему тексту.
    quoted: list[tuple[int, int]] = []
    stems: set[str] = set()
    for m in regs.ORG_GENERIC_QUOTED_RE.finditer(text):
        out.append(Entity("ORG", m.group(1), m.start(1), m.end(1),
                          m.group(1).strip('«»"').lower()))

    for rx in (regs.ORG_QUOTED_RE, regs.ORG_TRAILING_FORM_RE):
        for m in rx.finditer(text):
            name = m.group()
            if any(s <= m.start() and m.end() <= e for s, e in quoted):
                continue
            quoted.append((m.start(), m.end()))
            stems.update(_org_stems(name))
            out.append(
                Entity("ORG", name, m.start(), m.end(), " ".join(name.lower().split()))
            )

    # последним: «Ромашка» внутри 'АО «Ромashka»' не выдаем второй раз
    for m in regs.ORG_QUOTED_NAME_RE.finditer(text):
        name = m.group(1)
        if len(name) < 3:
            continue
        if any(e.type == "ORG" and e.start <= m.start(1) and m.end(1) <= e.end
               for e in out):
            continue
        out.append(Entity("ORG", name, m.start(1), m.end(1), name.lower()))

    # словарь: сначала название целиком, чтобы "Ромашка Россия" была одной меткой
    for name in org_names:
        flags = re.IGNORECASE if len(name) > 3 else 0
        pat = rf"(?<!{helpers.WORD_CHAR}){re.escape(name)}(?!{helpers.WORD_CHAR})"
        for m in re.finditer(pat, text, flags):
            if any(s <= m.start() and m.end() <= e for s, e in quoted):
                continue
            quoted.append((m.start(), m.end()))
            out.append(
                Entity("ORG", m.group(), m.start(), m.end(),
                       " ".join(name.lower().split()), source="dict")
            )

    # потом по словам - для названий, разорванных версткой
    for name in org_names:
        stems.update(_org_stems(name))
    stems |= set(_prefixes(stems))
    for stem in stems:
        # короткие - с учетом регистра: "ОКБ" да, "окб" нет
        flags = re.IGNORECASE if len(stem) > 3 else 0
        bound = helpers.WORD_CHAR
        for hit in re.finditer(rf"(?<!{bound}){re.escape(stem)}(?!{bound})", text, flags):
            if any(s <= hit.start() and hit.end() <= e for s, e in quoted):
                continue
            out.append(Entity("ORG", hit.group(), hit.start(), hit.end(), stem.lower()))

    for m in regs.OGRN_RE.finditer(text):
        d = m.group()
        if Validator.ogrn_ok(d):
            out.append(Entity("OGRN", d, m.start(), m.end(), d))

    uids: list[tuple[int, int, str]] = []
    for rx in (regs.UID_RE, regs.UID_LOOSE_RE):
        for m in rx.finditer(text):
            if len(re.findall(r"[0-9a-f]", m.group(), re.IGNORECASE)) >= helpers.UID_MIN_HEX:
                uids.append((m.start(), m.end(), m.group()))
    for start, end, txt in uids:
        if any(s <= start and end <= e and (s, e) != (start, end) for s, e, _ in uids):
            continue
        out.append(Entity("UID", txt, start, end, txt.lower()))

    # "паспорт" в 40 знаках перед номером или где угодно в документе про паспорта
    whole_doc = bool(regs.PASSPORT_DOC_CTX_RE.search(text))
    for m in regs.PASSPORT_RE.finditer(text):
        window = text[max(0, m.start() - 40):m.start()]
        if whole_doc or regs.PASSPORT_CTX_RE.search(window):
            out.append(Entity("PASSPORT", m.group(), m.start(), m.end(), digits(m.group())))

    named: list[tuple[int, int]] = []
    fio_words: set[str] = set()
    for rx in (regs.CAPS_FIO_RE, regs.INITIALS_RE):
        for m in rx.finditer(text):
            named.append((m.start(), m.end()))
            out.append(Entity("PERSON", m.group(), m.start(), m.end(),
                              " ".join(m.group().lower().split())))
            if rx is regs.CAPS_FIO_RE:
                fio_words.update(w for w in re.findall(r"[А-ЯЁ-]{4,}", m.group()))
    for m in regs.CAPS_PATR_RE.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in named):
            continue
        out.append(Entity("PERSON", m.group(), m.start(), m.end(), m.group().lower()))

    # одинокое слово капсом из уже найденного ФИО ("ВЕРШКОВА" на своей строке в PDF)
    known_fio = {w: w for w in fio_words} | _prefixes(fio_words)
    for hit in re.finditer(r"(?<![А-ЯЁA-Za-zа-яё-])[А-ЯЁ-]{4,}(?![А-ЯЁA-Za-zа-яё-])", text):
        if hit.group() not in known_fio:
            continue
        if any(s <= hit.start() and hit.end() <= e for s, e in named):
            continue
        out.append(Entity("PERSON", hit.group(), hit.start(), hit.end(), hit.group().lower()))

    # дубли одного спана: оставляем находку с более надежным источником
    rank = {"dict": 3, "requisite": 2, "": 1, "bare": 0}
    best: dict[tuple[str, int, int], Entity] = {}
    order: list[tuple[str, int, int]] = []
    for ent in out:
        mark = (ent.type, ent.start, ent.end)
        if mark not in best:
            best[mark] = ent
            order.append(mark)
        elif rank.get(ent.source, 1) > rank.get(best[mark].source, 1):
            best[mark] = ent
    return [best[m] for m in order]


def load_org_dict(path) -> tuple[str, ...]:
    """Словарь названий организаций: по одному на строку, '#' - комментарий."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"словарь организаций не найден: {p}")
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return tuple(names)
