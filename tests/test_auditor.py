"""Третий слой: аудитор подключается к Masker, Ollama - одна из реализаций.

Аудитор Ollama не должен оставлять модель висеть в памяти после прогона:
дефолт Ollama - keep_alive 5 минут, а после батч-аудита модель занимает
полтора-два гигабайта, которые на маленькой машине нужны другим процессам.
"""
import json

import httpx
import pytest

from pii_mask_enhanced.audit import OllamaAuditor
from pii_mask_enhanced.audit.base import entity_type, to_entities
from pii_mask_enhanced.engine.core import Masker


class _FakeResponse:
    def __init__(self, entities=()):
        self.entities = list(entities)

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": json.dumps({"entities": self.entities})}}


class _FakeClient:
    def __init__(self, calls, entities=()):
        self.calls, self.entities = calls, entities

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        self.calls.append((url, {}))
        return _FakeResponse()

    def post(self, url, json=None, **kw):
        self.calls.append((url, json or {}))
        return _FakeResponse(self.entities)


def _run(monkeypatch, text, entities=()):
    calls = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _FakeClient(calls, entities))
    found = OllamaAuditor(url="http://ollama:1", model="m").find(text)
    return calls, found


def test_client_ignores_environment_proxy(monkeypatch):
    """ALL_PROXY=socks5h://... в окружении не должен вставать между нами и Ollama.

    httpx разворачивает транспорт под прокси при создании клиента, до NO_PROXY,
    и без socksio падает ImportError - а наружу это выглядит как "Ollama недоступна".
    """
    kwargs = {}
    monkeypatch.setattr(httpx, "Client", lambda **kw: kwargs.update(kw) or _FakeClient([]))
    OllamaAuditor()._client(3.0)
    assert kwargs.get("trust_env") is False


def test_requests_go_to_configured_host_and_model(monkeypatch):
    calls, _ = _run(monkeypatch, "Иван Петров пришел на встречу.")
    url, body = calls[0]
    assert url == "http://ollama:1/api/chat" and body["model"] == "m"


def test_chunk_requests_carry_keep_alive(monkeypatch):
    calls, _ = _run(monkeypatch, "Иван Петров пришел на встречу.")
    chat = [body for url, body in calls if url.endswith("/api/chat")]
    assert chat, "не было ни одного запроса к модели"
    assert all(b.get("keep_alive") for b in chat), "keep_alive не задан - остается дефолт Ollama в 5 минут"


def test_model_unloaded_after_audit(monkeypatch):
    calls, _ = _run(monkeypatch, "Иван Петров пришел на встречу.")
    url, body = calls[-1]
    assert body.get("keep_alive") == 0, "последним запросом должна идти выгрузка модели"


def test_unload_failure_does_not_break_audit(monkeypatch):
    """Выгрузка - гигиена памяти, а не часть контракта: ее падение не роняет аудит."""

    class _FailingUnload(_FakeClient):
        def post(self, url, json=None, **kw):
            if (json or {}).get("keep_alive") == 0:
                raise OSError("ollama ушла")
            return super().post(url, json=json, **kw)

    monkeypatch.setattr(httpx, "Client", lambda **kw: _FailingUnload([]))
    assert OllamaAuditor().find("Иван Петров пришел на встречу.") == []


def test_find_returns_text_and_type(monkeypatch):
    _, found = _run(monkeypatch, "жена Оля", [{"text": "Оля", "type": "PERSON"}])
    assert found == [("Оля", "PERSON")]


# --- кандидаты -> находки ---

def test_any_registry_type_is_accepted():
    """Свой слой нейросети может вернуть особую категорию - тип реестра сохраняется."""
    assert entity_type("personal") == "PERSONAL"
    assert entity_type("ADDRESS") == "ADDRESS"
    assert entity_type("NICKNAME") == "TG"
    assert entity_type("непонятно") == "PERSON"


def test_candidates_become_every_literal_occurrence():
    text = "Оля пришла. Позвать Олю? Оля ушла."
    found = to_entities(text, [("Оля", "PERSON"), ("Мария", "PERSON"), ("х", "PERSON")])
    assert [(e.start, e.end) for e in found] == [(0, 3), (25, 28)]


# --- подключение к Masker ---

class _StubAuditor:
    def __init__(self, candidates, alive=True):
        self.candidates, self.alive, self.seen = candidates, alive, None

    def available(self):
        return self.alive

    def find(self, masked_text):
        self.seen = masked_text
        return self.candidates


def test_masker_masks_what_auditor_found():
    auditor = _StubAuditor([("диабет второго типа", "PERSONAL")])
    m = Masker(types=("PHONE",), ner=False, auditor=auditor)
    masked, mapping = m.mask_with_audit("тел 8 903 123-45-67, у него диабет второго типа")
    assert "+7 000" in auditor.seen, "аудитор получает уже замаскированный текст"
    assert "диабет" not in masked and "{{PERSONAL_1}}" in masked
    assert mapping["labels"]["{{PERSONAL_1}}"]["original"] == "диабет второго типа"


def test_audit_without_auditor_is_an_error():
    with pytest.raises(ValueError, match="аудитор не задан"):
        Masker(ner=False).mask_with_audit("текст")


def test_unavailable_auditor_fails_closed():
    with pytest.raises(RuntimeError, match="недоступен"):
        Masker(ner=False, auditor=_StubAuditor([], alive=False)).mask_with_audit("текст")
