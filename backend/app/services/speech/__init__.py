"""Local speech recognition services package."""

from app.services.speech.base import (
    EngineStatus,
    ModelValidationResult,
    SpeechEngine,
    TranscriptionResult,
    TranscriptionSegment,
)

__all__ = [
    "EngineStatus",
    "ModelValidationResult",
    "SpeechEngine",
    "TranscriptionResult",
    "TranscriptionSegment",
]
