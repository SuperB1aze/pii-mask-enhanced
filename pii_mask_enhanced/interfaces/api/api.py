"""HTTP-фасад микросервиса. Слушает только localhost (см. cli serve / systemd unit).

Сервис stateless: mapping приходит и уходит в теле запроса, на диске и в памяти
между запросами ничего не остается. Тела запросов не логируются - в них ПД.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ...engine.core import DEFAULT_TYPES, Masker
from .schemas import MaskRequest, MaskResponse, UnmaskRequest, UnmaskResponse

app = FastAPI(title="pii-mask-enhanced", docs_url=None, redoc_url=None)


@app.get("/health/live")
def health() -> dict:
    from ...detection.auditor import ollama_alive

    return {"status": "ok", "auditor": ollama_alive()}


@app.post("/mask", response_model=MaskResponse)
def mask(req: MaskRequest) -> MaskResponse:
    types = tuple(t.upper() for t in req.types) if req.types else DEFAULT_TYPES
    masker = Masker(types=types, ner=req.ner)
    try:
        if req.audit:
            masked, mapping = masker.mask_with_audit(req.text, req.mapping)
        else:
            masked, mapping = masker.mask(req.text, req.mapping)
    except RuntimeError as exc:  # аудит запрошен, Ollama лежит - fail-closed
        raise HTTPException(status_code=503, detail=str(exc))
    return MaskResponse(masked_text=masked, mapping=mapping)


@app.post("/unmask", response_model=UnmaskResponse)
def unmask(req: UnmaskRequest) -> UnmaskResponse:
    return UnmaskResponse(text=Masker(ner=False).unmask(req.text, req.mapping))
