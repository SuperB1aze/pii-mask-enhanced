"""Технические идентификаторы: IP, устройство (IMEI, MAC), сессия, строка браузера (USER_AGENT).

Формат у них строгий, поэтому они включены и по умолчанию, и в наборах. Граница -
версии программ, время, маски сети и суммы: на них маска ложиться не должна.
Адреса и токены в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.detection import presets
from pii_mask_enhanced.engine.core import Masker


def _mask(text: str, preset: str | None = None) -> str:
    types = presets.get(preset).types if preset else Masker().types
    return Masker(types=tuple(types), ner=False).mask(text)[0]


@pytest.mark.parametrize("preset", [None, "accounting"])
@pytest.mark.parametrize("src, expected", [
    ("вход с 192.168.10.5 в 12:30:45", "вход с {{IP_1}} в 12:30:45"),
    ("порт 192.168.1.1:8080", "порт {{IP_1}}:8080"),
    ("сервер 2001:db8::1", "сервер {{IP_1}}"),
    ("[2001:db8:85a3::8a2e:370:7334]:443", "[{{IP_1}}]:443"),
    ("IMEI: 490154203237518", "IMEI: {{DEVICE_1}}"),
    ("IMEI1 49-015420-323751-8", "IMEI1 {{DEVICE_1}}"),
    ("MAC 00:1A:2B:3C:4D:5E", "MAC {{DEVICE_1}}"),
    ("Cisco 001a.2b3c.4d5e", "Cisco {{DEVICE_1}}"),
    ("PHPSESSID=abc123def456ghi789; path=/", "PHPSESSID={{SESSION_1}}; path=/"),
    ("session_id: 9f8e7d6c5b4a3210", "session_id: {{SESSION_1}}"),
    ("api_key=sk_live_51HxYz9AbCdEf", "api_key={{SESSION_1}}"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
     "Authorization: Bearer {{SESSION_1}}"),
    ("User-Agent: okhttp/4.9.3", "User-Agent: {{USER_AGENT_1}}"),
])
def test_technical_masked(src, expected, preset):
    assert _mask(src, preset) == expected


def test_jwt_without_bearer():
    out = _mask("token в логе: eyJhbGciOiJub25lIn0.eyJzdWIiOiI0MiJ9.")
    assert "eyJ" not in out


def test_cookie_values_masked_names_kept():
    """По имени видно, что это за cookie, - его оставляем; закрываем значения."""
    out = _mask("Cookie: uid=abc123; _ym_uid=1672345678901234567; lang=ru")
    assert out == "Cookie: uid={{SESSION_1}}; _ym_uid={{SESSION_2}}; lang={{SESSION_3}}"


def test_set_cookie_attributes_kept():
    out = _mask("Set-Cookie: sid=xyz98765; Path=/; Max-Age=3600; HttpOnly")
    assert out == "Set-Cookie: sid={{SESSION_1}}; Path=/; Max-Age=3600; HttpOnly"


def test_user_agent_masked_whole():
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36")
    assert _mask(f"User-Agent: {ua}") == "User-Agent: {{USER_AGENT_1}}"
    assert _mask(f'ua="{ua}"') == 'ua="{{USER_AGENT_1}}"'


def test_mac_formats_one_label():
    """Один адрес в разной записи - одно устройство, одна метка."""
    out = _mask("MAC 00:1A:2B:3C:4D:5E, он же 001a.2b3c.4d5e и 00-1A-2B-3C-4D-5E")
    assert out == "MAC {{DEVICE_1}}, он же {{DEVICE_1}} и {{DEVICE_1}}"


@pytest.mark.parametrize("src", [
    "версия 3.10, сборка Chrome/1.2.3.4",
    "Python 3.12.10",
    "маска 255.255.255.0, localhost 127.0.0.1, 0.0.0.0",
    "встреча в 12:30:45",
    "сумма 1.234.567,00 руб.",
    "адрес 300.1.1.1 вне диапазона",
    "дата 01.02.2020",
    "номер 12-34-56-78-90-12",           # MAC через дефис без букв - не MAC
    "session: утро, token: нет",          # значение без цифр - не идентификатор
    "ОГРНИП 304500116000157",
])
def test_lookalikes_not_technical(src):
    out = Masker(ner=False).mask(src)[0]
    for label in ("{{IP_", "{{DEVICE_", "{{SESSION_", "{{USER_AGENT_"):
        assert label not in out, f"{src!r} -> {out!r}"


def test_token_in_technical_link_masked():
    """Ссылку на github не маскируем, но токен в ней - маскируем."""
    assert _mask("github.com/org/repo?token=abc123def456") == "github.com/org/repo?token={{SESSION_1}}"


@pytest.mark.parametrize("src", [
    "ссылка https://severbank-example.ru/doc/3f2a9c145b6d4e719a027c8de1f04b95",
    "https://severbank-example.ru/?token=3f2a9c145b6d4e71",
    "http://192.168.10.5/admin",
])
def test_identifier_inside_url_does_not_leave_domain_open(src):
    """hex, токен или IP внутри адреса уступают URL: иначе домен оставался открытым."""
    out = _mask(src, "accounting")
    assert "severbank-example" not in out and "192.168" not in out, out
    assert "{{URL_1}}" in out


def test_roundtrip_and_idempotent():
    """И с типом из двух слов: {{USER_AGENT_1}} должна узнаваться как метка, а не как текст."""
    m = Masker(ner=False)
    src = ("IP 192.168.10.5, IMEI: 490154203237518\n"
           "User-Agent: okhttp/4.9.3\n"
           "Cookie: sid=xyz98765")
    masked, mapping = m.mask(src)
    assert "{{USER_AGENT_1}}" in masked
    assert m.unmask(masked, mapping) == src
    assert m.mask(masked, mapping)[0] == masked
