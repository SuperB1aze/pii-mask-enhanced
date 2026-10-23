"""Технические идентификаторы: IP, устройство (IMEI, MAC), сессия, строка браузера (USER_AGENT).

Формат у них строгий, поэтому они включены и по умолчанию, и в наборах. Граница -
версии программ, время, маски сети и суммы: на них маска ложиться не должна.
Адреса и токены в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker

from masking import mask as _mask


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


# --- добивка: ОС, устройство, поведение на сайте, пользователь, баги ---

@pytest.mark.parametrize("src, expected", [
    # IMEI целиком: цифра слота - только вплотную или перед разделителем
    ("IMEI 490154203237518", "IMEI {{DEVICE_1}}"),
    ("IMEI1: 490154203237518", "IMEI1: {{DEVICE_1}}"),
    ("IMEI 2: 490154203237518", "IMEI 2: {{DEVICE_1}}"),
    ("IMSI 250011234567890", "IMSI {{DEVICE_1}}"),
    ("ICCID 8970101234567890123", "ICCID {{DEVICE_1}}"),
    # ОС
    ("os: Android 13", "os: {{DEVICE_1}}"),
    ("OS: iOS 17.2", "OS: {{DEVICE_1}}"),
    ("os_version=13", "os_version={{DEVICE_1}}"),
    ("platform: Windows 10, browser: Chrome", "platform: {{DEVICE_1}}, browser: Chrome"),
    # идентификатор и модель устройства
    ("device_id=a1b2c3d4e5f6a7b8", "device_id={{DEVICE_1}}"),
    ("android_id: 9774d56d682e549c", "android_id: {{DEVICE_1}}"),
    ("serial: R58N12ABCDE", "serial: {{DEVICE_1}}"),
    ("модель SM-G991B", "модель {{DEVICE_1}}"),
    ("model: iPhone 14 Pro, os: iOS 17", "model: {{DEVICE_1}}, os: {{DEVICE_2}}"),
    ("модель телефона iPhone 14 Pro на базе iOS", "модель телефона {{DEVICE_1}} на базе iOS"),
    # строка мобильного клиента
    ("Dalvik/2.1.0 (Linux; U; Android 13; SM-G991B)", "{{USER_AGENT_1}}"),
    ("MyBank/5.2.1 (iPhone; iOS 17.2; Scale/3.00)", "{{USER_AGENT_1}}"),
    ("MyBank/5 CFNetwork/1410.0.3 Darwin/22.6.0", "{{USER_AGENT_1}}"),
    # поведение на сайте
    ("pageviews: 15", "pageviews: {{BEHAVIOR_1}}"),
    ('"pageviews": 15', '"pageviews": {{BEHAVIOR_1}}'),
    ("просмотрено страниц: 15", "просмотрено страниц: {{BEHAVIOR_1}}"),
    ("session_duration: 00:12:34", "session_duration: {{BEHAVIOR_1}}"),
    ("time_on_site=754", "time_on_site={{BEHAVIOR_1}}"),
    ("время на сайте: 12 мин", "время на сайте: {{BEHAVIOR_1}}"),
    ("?text=купить+квартиру&lr=213", "?text={{BEHAVIOR_1}}&lr=213"),
    ("q=ипотека+сбербанк", "q={{BEHAVIOR_1}}"),
    # запрос внутри полного адреса закрывается вместе с хостом
    ("https://yandex.ru/search/?text=купить+квартиру", "{{URL_1}}"),
    ("referrer=https%3A%2F%2Fsite.ru%2Fpage", "referrer={{URL_1}}"),
    # пользователь и посетитель
    ("user_id=1234567", "user_id={{SESSION_1}}"),
    ("uid: 1234567", "uid: {{SESSION_1}}"),
    ("client_id=1234567890.1700000000", "client_id={{SESSION_1}}"),
    ("fingerprint: 3f2a9c145b6d4e71", "fingerprint: {{SESSION_1}}"),
    # координаты из лога
    ("geo: 55.75,37.61", "geo: {{ADDRESS_1}}"),
])
def test_technical_by_key(src, expected):
    assert _mask(src) == expected


def test_json_values_are_not_orgs():
    """Латинское значение поля JSON - техническое, а не название организации в кавычках."""
    assert _mask('{"name": "Chrome", "os": "Android 13"}') == \
        '{"name": "Chrome", "os": "{{DEVICE_1}}"}'


def test_cyrillic_json_value_still_an_org():
    assert _mask('{"company": "Ромашка"}') == '{"company": "{{ORG_1}}"}'


@pytest.mark.parametrize("src", [
    "okhttp/4.9.3",                          # библиотека, а не устройство
    "curl/8.4.0",
    "Accept-Language: ru-RU,ru;q=0.9",       # q - вес языка, а не запрос
    "device_id: unknown",                    # без цифры - не идентификатор
    "модель 2025 года",
    "модель автомобиля Kia Rio",
    "текст про OS и платформу",
])
def test_technical_lookalikes_untouched(src):
    assert _mask(src) == src


# --- внутренняя сеть: хост во внутренней зоне и сетевой путь ---

@pytest.mark.parametrize("src, expected", [
    ("подключиться к srv-db01.corp.local:5432", "подключиться к {{URL_1}}:5432"),
    ("fs01.lan", "{{URL_1}}"),
    ("портал app.internal", "портал {{URL_1}}"),
    ("nas.home.arpa", "{{URL_1}}"),
    (r"файл лежит в \\fileserver01\share\Отдел кадров\отчет.xlsx, см.",
     "файл лежит в {{URL_1}}, см."),
    (r"\\10.0.5.1\backup", "{{URL_1}}"),
    (r"путь \\FS01\Docs\2024", "путь {{URL_1}}"),
    # хост после логина и пароля в адресе подключения
    ("postgresql://app:pw@db.corp.local:5432/main",
     "postgresql://{{PERSON_ID_1}}:{{SECRET_1}}@{{URL_1}}:5432/main"),
])
def test_internal_host_and_unc_path(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    r"C:\Windows\system32",                  # локальный путь - не адрес в сети
    r"строка с \\n внутри",                 # экранированный перевод строки в JSON
    "версия 1.2.local",                      # в имени нет букв
    "сервер srv-db01",                       # имя без зоны - нейросети
    "localhost",
])
def test_internal_host_lookalikes_untouched(src):
    assert _mask(src) == src
