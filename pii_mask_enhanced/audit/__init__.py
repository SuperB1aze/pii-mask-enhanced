"""Третий слой маскировки: аудитор по уже замаскированному тексту."""
from .base import PROMPT, SCHEMA, Auditor, chunks
from .ollama import OllamaAuditor
