"""HTTP-фасад микросервиса. Слушает только localhost (см. cli serve / systemd unit).

Сервис stateless: mapping приходит и уходит в теле запроса, на диске и в памяти
между запросами ничего не остается. Тела запросов не логируются - в них ПД.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ...engine.core import Masker
from ...engine.settings import Options, build_masker, type_names
from .schemas import MaskRequest, MaskResponse, UnmaskRequest, UnmaskResponse

app = FastAPI(title="pii-mask-enhanced", docs_url=None, redoc_url=None)


@app.get("/health/live")
def health() -> dict:
    from ...detection.auditor import ollama_alive

    return {"status": "ok", "auditor": ollama_alive()}


@app.post("/mask", response_model=MaskResponse)
def mask(req: MaskRequest) -> MaskResponse:
    opts = Options(
        preset=req.preset,
        types=type_names(req.types),
        ner=req.ner,
        ner_types=type_names(req.ner_types),
        ner_org_needs_form=req.ner_org_needs_form,
        ner_person_needs_fio=req.ner_person_needs_fio,
        inn_needs_label=req.inn_needs_label,
        auto_profile=req.auto_profile,
        org_names=tuple(req.org_names),
        supported_names=tuple(req.supported_names),
    )
    try:
        masker, _ = build_masker(opts, lambda: req.text)
    except ValueError as exc:  # неизвестный набор или тип
        raise HTTPException(status_code=400, detail=str(exc))
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
