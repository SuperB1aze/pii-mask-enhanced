"""Серийный номер сертификата электронной подписи.

Найден в акте маркетплейса: рядом с подписантом стоят длинные шестнадцатеричные
номера сертификатов. Формально это не ФИО, но сертификат выдан конкретному
человеку и опознает его не хуже фамилии - в обезличенном документе ему не место.

Номера в тестах выдуманные: репозиторий публичный.
"""
from pii_mask.core import Masker


def _mask(text: str, types=("CERT",)) -> str:
    return Masker(types=types, ner=False).mask(text)[0]


def test_certificate_serial_masked():
    for serial in ("226C543276E8EFBF4E1036FD01", "029275F80053B383BF4E5A0BFB"):
        assert serial not in _mask(f"Сертификат {serial} 11.08.2026")


def test_short_hex_untouched():
    """Короткая шестнадцатеричная строка - это что угодно, не сертификат."""
    src = "код 1A2B3C и еще DEAD"
    assert _mask(src) == src


def test_plain_number_untouched():
    """Длинное десятичное число - не сертификат: у него другой распознаватель."""
    src = "сумма 12345678901234567890"
    assert _mask(src) == src


def test_uuid_masked_as_uid():
    """UUID уже поддержан типом UID - проверяем, что он реально ловится."""
    out = _mask("идентификатор 99d4c0ac-353e-4a1c-b60d-e498f7505bfd",
                types=("UID",))
    assert "99d4c0ac" not in out
