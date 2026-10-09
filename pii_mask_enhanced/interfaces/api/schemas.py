from pydantic import BaseModel


class MaskRequest(BaseModel):
    text: str
    mapping: dict | None = None
    audit: bool = False
    ner: bool = True
    # те же настройки, что у CLI (engine/settings.py)
    preset: str | None = None
    types: list[str] | None = None
    ner_types: list[str] | None = None
    ner_org_needs_form: bool = False
    ner_person_needs_fio: bool = False
    inn_needs_label: bool = False
    auto_profile: bool = False
    org_names: list[str] = []
    supported_names: list[str] = []


class MaskResponse(BaseModel):
    masked_text: str
    mapping: dict


class UnmaskRequest(BaseModel):
    text: str
    mapping: dict


class UnmaskResponse(BaseModel):
    text: str
