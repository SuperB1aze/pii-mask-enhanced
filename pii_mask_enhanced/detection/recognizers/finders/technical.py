"""Технические идентификаторы: IP, устройство, сессия, строка браузера."""
from __future__ import annotations

import ipaddress

from ...registry import sources
from .. import regulars as regs
from ..entity import Entity, digits


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


def devices(text: str) -> list[Entity]:
    out = [Entity("DEVICE", m.group(1), m.start(1), m.end(1), digits(m.group(1)),
                  source=sources.REQUISITE)
           for m in regs.IMEI_RE.finditer(text)]
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


def user_agents(text: str) -> list[Entity]:
    found = [(m.start(1), m.group(1)) for m in regs.USER_AGENT_HEADER_RE.finditer(text)]
    found += [(m.start(), m.group()) for m in regs.USER_AGENT_RE.finditer(text)]
    out = []
    for start, value in found:
        value = value.rstrip(" \t,;")
        out.append(Entity("USER_AGENT", value, start, start + len(value), value))
    return out
