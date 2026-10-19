"""Технические идентификаторы: IP, устройство, сессия, строка браузера."""
from __future__ import annotations

import ipaddress
import math
from collections import Counter

from ...registry import sources
from .. import regulars as regs
from ..entity import Entity, digits, text_key


def _ip_ok(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (addr.is_loopback or addr.is_unspecified or addr.is_reserved or addr.is_multicast)


def ips(text: str) -> list[Entity]:
    out = []
    for rx, kind in ((regs.IPV4_RE, ipaddress.IPv4Address), (regs.IPV6_RE, ipaddress.IPv6Address)):
        for m in rx.finditer(text):
            try:
                addr = kind(m.group())
            except ValueError:
                continue        # "300.1.1.1", "12:30:45", MAC
            if _ip_ok(addr):
                out.append(Entity("IP", m.group(), m.start(), m.end(), addr.compressed))
    return out


def _by_key(etype: str, rx, text: str, key=text_key) -> list[Entity]:
    """Значение из первой непустой группы: ключ лога, поле JSON, параметр запроса."""
    out = []
    for m in rx.finditer(text):
        g = next(i for i in range(1, (m.lastindex or 0) + 1) if m.group(i))
        value = m.group(g).rstrip(" \t.")
        out.append(Entity(etype, value, m.start(g), m.start(g) + len(value), key(value),
                          source=sources.REQUISITE))
    return out


def devices(text: str) -> list[Entity]:
    out = [Entity("DEVICE", m.group(1), m.start(1), m.end(1), digits(m.group(1)),
                  source=sources.REQUISITE)
           for m in regs.IMEI_RE.finditer(text)]
    # SIM, ОС, идентификатор и модель устройства по ключу
    for rx in (regs.SIM_RE, regs.OS_RE, regs.DEVICE_ID_RE, regs.DEVICE_MODEL_RE,
               regs.DEVICE_MODEL_RU_RE):
        out += _by_key("DEVICE", rx, text)
    for m in regs.MAC_RE.finditer(text):
        mac = m.group()
        # "12-34-56-78-90-12" без единой буквы - скорее номер; с двоеточиями - MAC
        if m.group(1) != ":" and not any(c.isalpha() for c in mac):
            continue
        out.append(Entity("DEVICE", mac, m.start(), m.end(),
                          "".join(c for c in mac if c.isalnum()).lower()))
    return out


def sessions(text: str) -> list[Entity]:
    out = [Entity("SESSION", m.group(), m.start(), m.end(), m.group())
           for m in regs.JWT_RE.finditer(text)]
    for rx in (regs.SESSION_RE, regs.BEARER_RE):
        out += [Entity("SESSION", m.group(1), m.start(1), m.end(1), m.group(1),
                       source=sources.REQUISITE)
                for m in rx.finditer(text)]
    for header in regs.COOKIE_HEADER_RE.finditer(text):
        base = header.start(1)
        for pair in regs.COOKIE_PAIR_RE.finditer(header.group(1)):
            if pair.group(1).lower() in regs.COOKIE_ATTRS:
                continue
            value = pair.group(2).rstrip()
            start = base + pair.start(2)
            out.append(Entity("SESSION", value, start, start + len(value), value,
                              source=sources.REQUISITE))
    return out


def behavior(text: str) -> list[Entity]:
    """Поведение на сайте: просмотры, время, поисковый запрос; referrer - адрес целиком."""
    out = []
    for rx in (regs.PAGEVIEWS_RE, regs.DURATION_RE, regs.SEARCH_QUERY_RE):
        out += _by_key("BEHAVIOR", rx, text)
    return out + _by_key("URL", regs.REFERRER_RE, text)


def credentials(text: str) -> list[Entity]:
    """Логин и пароль парой: "логин/пароль: a / b", "https://a:b@host", доменное "CORP\\a"."""
    out = []
    for rx in (regs.LOGIN_PASSWORD_RE, regs.URL_CREDS_RE):
        for m in rx.finditer(text):
            out.append(Entity("PERSON_ID", m.group(1), m.start(1), m.end(1), text_key(m.group(1)),
                              source=sources.REQUISITE))
            out.append(Entity("SECRET", m.group(2), m.start(2), m.end(2), m.group(2),
                              source=sources.REQUISITE))
    out += [Entity("PERSON_ID", m.group(), m.start(), m.end(), text_key(m.group()))
            for m in regs.DOMAIN_LOGIN_RE.finditer(text)]
    return out


def _entropy(value: str) -> float:
    """Бит на символ (Шеннон): у ключей и токенов от ~3.5, у слов и "default_value" меньше."""
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


# порог энтропии и обязательная смесь классов символов - как у gitleaks
_SECRET_ENTROPY = 3.5


def _looks_random(value: str) -> bool:
    classes = sum(any(f(c) for c in value) for f in (str.isdigit, str.islower, str.isupper))
    return classes >= 2 and _entropy(value) >= _SECRET_ENTROPY


def secrets(text: str) -> list[Entity]:
    """Хэши паролей, ключи шифрования, токены сервисов."""
    out = [Entity("SECRET", m.group(), m.start(), m.end(), m.group())
           for rx in (regs.PASSWORD_HASH_RE, regs.API_TOKEN_RE) for m in rx.finditer(text)]
    out += [Entity("SECRET", m.group(1), m.start(1), m.end(1), m.group(1).lower(),
                   source=sources.REQUISITE)
            for m in regs.HEX_HASH_RE.finditer(text)]
    for m in regs.NTLM_DUMP_RE.finditer(text):
        out.append(Entity("PERSON_ID", m.group(1), m.start(1), m.end(1), text_key(m.group(1))))
        out += [Entity("SECRET", m.group(g), m.start(g), m.end(g), m.group(g).lower())
                for g in (2, 3)]
    for m in regs.PEM_RE.finditer(text):
        # тело без переводов строки по краям: заголовки остаются на своих строках
        body = m.group(2)
        lead = len(body) - len(body.lstrip())
        value = body.strip()
        if value:
            start = m.start(2) + lead
            out.append(Entity("SECRET", value, start, start + len(value), value))
    for m in regs.SSH_KEY_RE.finditer(text):
        out.append(Entity("SECRET", m.group(1), m.start(1), m.end(1), m.group(1)))
        if m.group(2):
            out.append(Entity("PERSON_ID", m.group(2), m.start(2), m.end(2),
                              text_key(m.group(2))))
    out += [Entity("SECRET", m.group(1), m.start(1), m.end(1), m.group(1),
                   source=sources.REQUISITE)
            for m in regs.SECRET_KEY_RE.finditer(text) if _looks_random(m.group(1))]
    return out


def user_agents(text: str) -> list[Entity]:
    found = [(m.start(1), m.group(1)) for m in regs.USER_AGENT_HEADER_RE.finditer(text)]
    found += [(m.start(), m.group())
              for rx in (regs.USER_AGENT_RE, regs.APP_AGENT_RE) for m in rx.finditer(text)]
    out = []
    for start, value in found:
        value = value.rstrip(" \t,;")
        out.append(Entity("USER_AGENT", value, start, start + len(value), value))
    return out
