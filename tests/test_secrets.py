"""Данные карты и секреты: магнитная полоса, хэши паролей, ключи шифрования, токены.

Форматы узнаются по префиксу или структуре. Где формат общий (hex-хэш, строка
конфига), нужна подпись. Ключи и токены в тестах выдуманные.
"""
import pytest

from pii_mask_enhanced.engine.core import Masker


def _mask(text: str) -> str:
    return Masker(ner=False).mask(text)[0]


# --- магнитная полоса ---

@pytest.mark.parametrize("src, expected", [
    (";4276380012345679=27121010000000000000?", "{{CARD_1}}"),
    ("%B4276380012345679^IVANOV/IVAN^2712101000000000000?", "{{CARD_1}}"),
    ("track2 4276380012345679=2712101000000", "track2 {{CARD_1}}"),   # из лога, без ";"
])
def test_card_track_masked_whole(src, expected):
    """Кроме номера в дорожке имя, срок и CVV1: закрывается целиком."""
    assert _mask(src) == expected


def test_card_track_shares_label_with_card_number():
    out = _mask("карта 4276380012345679, дорожка ;4276380012345679=27121010000000000000?")
    assert out == "карта {{CARD_1}}, дорожка {{CARD_1}}"


def test_track_without_sentinel_needs_luhn():
    assert _mask("x=1234567890123=1234567") == "x=1234567890123=1234567"


# --- хэши паролей ---

@pytest.mark.parametrize("src, expected", [
    ("hash $2b$12$KIXxPfnK9vZ6aJ0sQe2Q8uR2nBzYk3cF1mWnGvXyZ1aBcDeFgHiJk", "hash {{SECRET_1}}"),
    ("$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$Rk2h3a9QvF0x1yZp8wE7tA", "{{SECRET_1}}"),
    ("$6$rounds=5000$saltsalt$Lq2bQm9V8x7c6z5a4s3d2f1g", "{{SECRET_1}}"),
    ("pbkdf2_sha256$600000$abcDEF123$Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==", "{{SECRET_1}}"),
    ("md5: 5f4dcc3b5aa765d61d8327deb882cf99", "md5: {{SECRET_1}}"),
    ("sha256 9F86D081884C7D659A2FEAA0C55AD015A3BF4F1B2B0B822CD15D6C15B0F00A08",
     "sha256 {{SECRET_1}}"),
    ("password_hash=5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8", "password_hash={{SECRET_1}}"),
    ("Administrator:500:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::",
     "{{PERSON_ID_1}}:500:{{SECRET_1}}:{{SECRET_2}}:::"),
])
def test_password_hash_masked(src, expected):
    assert _mask(src) == expected


# --- ключи и токены ---

@pytest.mark.parametrize("src, expected", [
    ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nAbCdEf==\n-----END PRIVATE KEY-----",
     "-----BEGIN PRIVATE KEY-----\n{{SECRET_1}}\n-----END PRIVATE KEY-----"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----",
     "-----BEGIN OPENSSH PRIVATE KEY-----\n{{SECRET_1}}\n-----END OPENSSH PRIVATE KEY-----"),
    ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7", "ssh-rsa {{SECRET_1}}"),
    ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMq ivanov@laptop",
     "ssh-ed25519 {{SECRET_1}} {{PERSON_ID_1}}"),
    ("AKIAIOSFODNN7EXAMPLE", "{{SECRET_1}}"),
    ("ghp_1234567890abcdefghijABCDEFGHIJ123456", "{{SECRET_1}}"),
    ("ключ sk-ant-api03-AbCdEf1234567890GhIjKlMnOp", "ключ {{SECRET_1}}"),
    ("xoxb-123456789012-abcdefABCDEF", "{{SECRET_1}}"),
    ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "{{SECRET_1}}"),
    ("bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1", "bot {{SECRET_1}}"),
    ("client_secret=Zx9vQ2mP7kL4tR8wY1nB3cF6", "client_secret={{SECRET_1}}"),
    ("AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "AWS_SECRET_KEY={{SECRET_1}}"),
    ("секретный ключ: aB3dE6gH9jK2mN5pQ8", "секретный ключ: {{SECRET_1}}"),
])
def test_key_or_token_masked(src, expected):
    assert _mask(src) == expected


@pytest.mark.parametrize("src", [
    "цена $1$ за штуку",
    "файл 5f4dcc3b5aa765d61d8327deb882cf99",       # hex без подписи - контрольная сумма
    "secret: none",
    "SECRET_KEY=default_value_here",                # низкая энтропия - заглушка
    "public_key=ABCDEFGHIJKLMNOP1234",              # открытый ключ по имени переменной
    "sk-learn is a library",
    "ключевой момент: важно",
])
def test_secret_lookalikes_untouched(src):
    assert _mask(src) == src
