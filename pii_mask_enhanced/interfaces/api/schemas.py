from pydantic import BaseModel

class MaskRequest(BaseModel):
    text: str
    mapping: dict | None = None
    audit: bool = False
    ner: bool = True
    types: list[str] | None = None


class MaskResponse(BaseModel):
    masked_text: str
    mapping: dict


class UnmaskRequest(BaseModel):
    text: str
    mapping: dict


class UnmaskResponse(BaseModel):
    text: str