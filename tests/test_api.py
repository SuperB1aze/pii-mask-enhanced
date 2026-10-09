"""HTTP-фасад: roundtrip через API, health, защита от недоступного аудитора."""
from fastapi.testclient import TestClient

from pii_mask_enhanced.interfaces.api.api import app

client = TestClient(app)


def test_health():
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_mask_unmask_roundtrip():
    src = "Звонил Петр Орлов, тел +7 915 000-11-22"
    r = client.post("/mask", json={"text": src})
    assert r.status_code == 200
    body = r.json()
    assert "Орлов" not in body["masked_text"]
    assert "+7 915 000-11-22" not in body["masked_text"]

    r2 = client.post("/unmask", json={"text": body["masked_text"], "mapping": body["mapping"]})
    assert r2.status_code == 200
    assert "Петр Орлов" in r2.json()["text"]
    assert "+7 915 000-11-22" in r2.json()["text"]


def test_audit_fail_closed(monkeypatch):
    # Ollama лежит + запрошен audit -> 503, а не тихая маскировка без аудита
    import pii_mask_enhanced.detection.auditor as auditor

    monkeypatch.setattr(auditor, "ollama_alive", lambda *a, **k: False)
    r = client.post("/mask", json={"text": "Иван Петров", "audit": True})
    assert r.status_code == 503


def test_preset_works_over_http():
    """Набор знает сервис: через API тот же документ маскируется так же, как через CLI."""
    src = "Артикул 1063391630, поставщик ИНН 6083778353"
    plain = client.post("/mask", json={"text": src, "ner": False}).json()["masked_text"]
    strict = client.post("/mask", json={"text": src, "ner": False,
                                        "preset": "accounting"}).json()["masked_text"]
    assert "1063391630" not in plain
    assert "1063391630" in strict, "в наборе артикул без подписи ИНН не маскируется"
    assert "6083778353" not in strict


def test_unknown_type_and_preset_are_rejected():
    assert client.post("/mask", json={"text": "x", "types": ["INNN"]}).status_code == 400
    assert client.post("/mask", json={"text": "x", "preset": "нет"}).status_code == 400
