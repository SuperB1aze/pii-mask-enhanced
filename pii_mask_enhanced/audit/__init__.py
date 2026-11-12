"""Третий слой маскировки: аудитор по уже замаскированному тексту."""
from .base import AuditCandidate, PROMPT, SCHEMA, AuditError, Auditor, chunk_ranges, chunks
from .ollama import OllamaAuditor
