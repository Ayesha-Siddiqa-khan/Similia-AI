"""Configuration persistence for local speech-to-text recognition."""

import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.services.speech.base import SpeechSettingsModel

DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".speech_settings.json"


def get_default_model_path() -> str:
    """Return a configured model directory, or empty when the user must choose one.

    Model weights are deliberately never bundled: they are multi-gigabyte and
    licensed separately. The desktop app sets SIMILIA_SPEECH_MODEL_PATH from its
    saved configuration; otherwise the user picks a folder in Settings.
    """
    override = os.environ.get("SIMILIA_SPEECH_MODEL_PATH", "").strip()
    if override and Path(override).is_dir():
        return str(Path(override).resolve())
    return ""


def get_default_python_executable() -> str:
    """Return the interpreter that runs the speech worker.

    A packaged build ignores this value and re-uses its own executable (see
    FasterWhisperEngine); in development the project venv contains
    faster-whisper after `uv sync --group speech`.
    """
    env_override = os.environ.get("SIMILIA_SPEECH_PYTHON_PATH", "").strip()
    if env_override and Path(env_override).is_file():
        return env_override
    return sys.executable


def get_config_file_path() -> Path:
    """Return the path to the speech settings file."""
    custom_path = os.environ.get("SIMILIA_SPEECH_CONFIG_PATH", "").strip()
    if custom_path:
        return Path(custom_path)
    return DEFAULT_CONFIG_FILE


def read_speech_settings() -> SpeechSettingsModel:
    """Read the persisted settings without applying defaults or writing back."""
    data = json.loads(get_config_file_path().read_text(encoding="utf-8"))
    settings = SpeechSettingsModel.model_validate(data)
    settings.python_executable = get_default_python_executable()
    return settings


def load_speech_settings() -> SpeechSettingsModel:
    """Load the speech file, falling back to the legacy path only for an empty setting."""
    interpreter = get_default_python_executable()
    settings = SpeechSettingsModel(python_executable=interpreter)
    try:
        settings = read_speech_settings()
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        # A GET or restart must never replace an unreadable settings file with defaults.
        return settings.model_copy(update={"model_path": get_default_model_path()})

    if not settings.model_path.strip() and (legacy_path := get_default_model_path()):
        settings.model_path = legacy_path
        try:
            save_speech_settings(settings)
        except OSError:
            # Keep the legacy fallback usable until the user can save it.
            pass
    return settings


def save_speech_settings(settings: SpeechSettingsModel) -> None:
    """Persist settings to local JSON file."""
    config_file = get_config_file_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_file.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(settings.model_dump(), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, config_file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
