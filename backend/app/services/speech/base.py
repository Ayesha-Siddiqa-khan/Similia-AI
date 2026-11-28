"""Pluggable speech recognition interface definitions and data structures."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ModelValidationResult(BaseModel):
    """Result of validating a candidate model directory."""

    valid: bool
    error: str | None = None
    engine: str = "faster-whisper"
    model_type: str | None = None
    architecture: str | None = None
    model_path: str = ""
    size_bytes: int = 0
    size_mb: float = 0.0
    files_found: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)


class TranscriptionSegment(BaseModel):
    """Timestamped segment from a transcription."""

    id: int
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    """Output from transcribing an audio recording."""

    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float = 0.0
    segments: list[TranscriptionSegment] = Field(default_factory=list)


class EngineStatus(BaseModel):
    """Real-time status of the local speech recognition engine."""

    status: str = "unloaded"  # unloaded | loading | ready | transcribing | error
    engine: str = "faster-whisper"
    model_path: str | None = None
    device: str = "auto"
    compute_type: str = "auto"
    idle_seconds_remaining: int | None = None
    idle_timeout_seconds: int = 600
    memory_rss_mb: float | None = None
    last_active_timestamp: float | None = None
    error_message: str | None = None
    python_executable: str | None = None
    supported_devices: list[str] = Field(default_factory=lambda: ["cpu", "cuda", "auto"])
    supported_languages: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"code": "auto", "label": "Auto-detect (English / Urdu)"},
            {"code": "en", "label": "English"},
            {"code": "ur", "label": "Urdu (اردو)"},
        ]
    )


class SpeechSettingsModel(BaseModel):
    """Persistent user settings for local speech recognition."""

    enabled: bool = True
    engine: str = "faster-whisper"
    model_path: str = ""
    device: str = "auto"  # auto | cpu | cuda
    compute_type: str = "auto"  # auto | int8 | float16 | float32 | default
    idle_timeout_seconds: int = 600  # Default 10 minutes
    default_language: str = "auto"  # auto | en | ur
    python_executable: str = ""  # Optional path to specific python runtime


@runtime_checkable
class SpeechEngine(Protocol):
    """Pluggable interface for local speech recognition engines."""

    def validate_model(self, model_path: Path) -> ModelValidationResult:
        """Inspect a directory to check if it contains valid model weights."""
        ...

    def load(self, model_path: Path, device: str, compute_type: str) -> None:
        """Load model into memory on the target device."""
        ...

    def unload(self) -> None:
        """Unload model and release memory."""
        ...

    def is_loaded(self) -> bool:
        """Whether the model is currently loaded in memory."""
        ...

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        task: str = "transcribe",
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file."""
        ...
