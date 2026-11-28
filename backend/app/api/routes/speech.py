"""API routes for local speech recognition, settings, validation, and offline transcription."""

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.auth import require_practitioner
from app.core.paths import data_dir
from app.services.speech.base import (
    EngineStatus,
    ModelValidationResult,
    SpeechSettingsModel,
    TranscriptionResult,
)
from app.services.speech.manager import get_speech_manager

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 24 * 1024 * 1024

router = APIRouter(prefix="/api/speech", tags=["speech"])


class ValidatePathRequest(BaseModel):
    model_path: str = Field(..., description="Directory path containing local model weights")


class SpeechStatusResponse(BaseModel):
    settings: SpeechSettingsModel
    status: EngineStatus


@router.get("/settings", response_model=SpeechStatusResponse)
def get_settings(
    _user: Annotated[str, Depends(require_practitioner)],
) -> SpeechStatusResponse:
    """Get current speech recognition configuration and real-time engine status."""
    manager = get_speech_manager()
    return SpeechStatusResponse(
        settings=manager.get_settings(),
        status=manager.get_status(),
    )


@router.put("/settings", response_model=SpeechStatusResponse)
def update_settings(
    request: SpeechSettingsModel,
    _user: Annotated[str, Depends(require_practitioner)],
) -> SpeechStatusResponse:
    """Update and persist speech recognition settings."""
    manager = get_speech_manager()
    try:
        updated = manager.update_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            503, "Could not save speech settings. Check write access and try again."
        ) from exc
    return SpeechStatusResponse(
        settings=updated,
        status=manager.get_status(),
    )


@router.post("/validate", response_model=ModelValidationResult)
def validate_model_path(
    request: ValidatePathRequest,
    _user: Annotated[str, Depends(require_practitioner)],
) -> ModelValidationResult:
    """Validate that a local directory contains compatible Faster-Whisper weights."""
    manager = get_speech_manager()
    return manager.validate_model_path(request.model_path)


@router.post("/load", response_model=SpeechStatusResponse)
def load_model(
    _user: Annotated[str, Depends(require_practitioner)],
) -> SpeechStatusResponse:
    """Explicitly load the configured speech model into memory."""
    manager = get_speech_manager()
    try:
        manager.load_model()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to load speech model: {exc}",
        ) from exc
    return SpeechStatusResponse(
        settings=manager.get_settings(),
        status=manager.get_status(),
    )


@router.post("/unload", response_model=SpeechStatusResponse)
def unload_model(
    _user: Annotated[str, Depends(require_practitioner)],
) -> SpeechStatusResponse:
    """Immediately unload the speech model and release all RAM/VRAM back to the OS."""
    manager = get_speech_manager()
    manager.unload()
    return SpeechStatusResponse(
        settings=manager.get_settings(),
        status=manager.get_status(),
    )


@router.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    _user: Annotated[str, Depends(require_practitioner)],
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    task: str = Form("transcribe"),
    initial_prompt: str | None = Form(None),
) -> TranscriptionResult:
    """Transcribe an uploaded speech recording locally.

    Loads the model on-demand if idle, resets the 10-minute idle countdown,
    and returns recognized text without cloud transmission.
    """
    manager = get_speech_manager()

    # Determine extension
    suffix = ".webm"
    if audio.filename:
        found_suffix = Path(audio.filename).suffix.lower()
        if found_suffix in [".webm", ".wav", ".ogg", ".mp3", ".m4a", ".mp4", ".flac"]:
            suffix = found_suffix

    # Save audio stream to temporary file
    audio_dir = data_dir() / "audio-tmp"
    audio_dir.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(dir=audio_dir, delete=False, suffix=suffix)
    try:
        content = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio recording exceeds 24 MB.")
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Audio recording was empty. Please record again.",
            )
        temp_file.write(content)
        temp_file.flush()
        temp_file.close()

        # Perform local offline transcription
        result = await run_in_threadpool(
            manager.transcribe,
            audio_path=Path(temp_file.name),
            language=language,
            task=task,
            initial_prompt=initial_prompt,
        )
        return result

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Local speech transcription failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech transcription failed: {exc}",
        ) from exc
    finally:
        # Clean up temp audio file
        try:
            temp_file.close()
            Path(temp_file.name).unlink(missing_ok=True)
        except Exception:
            pass
