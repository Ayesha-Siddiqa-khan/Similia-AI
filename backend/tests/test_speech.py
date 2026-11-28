"""Tests for local speech recognition engine, validation, idle countdown, and API endpoints."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_practitioner
from app.main import create_app
from app.services.speech import manager as speech_manager
from app.services.speech.base import (
    ModelValidationResult,
    SpeechSettingsModel,
    TranscriptionResult,
    TranscriptionSegment,
)
from app.services.speech.config import (
    get_default_model_path,
    load_speech_settings,
    save_speech_settings,
)
from app.services.speech.manager import SpeechManager, get_speech_manager
from app.services.speech.worker import decode_audio, validate_model_path


@pytest.mark.parametrize(("extension", "codec"), [("wav", "pcm_s16le"), ("webm", "opus")])
def test_decoder_produces_mono_pcm_for_recorder_formats(
    tmp_path: Path, extension: str, codec: str
) -> None:
    av = pytest.importorskip("av")
    numpy = pytest.importorskip("numpy")
    path = tmp_path / f"recording.{extension}"
    with av.open(str(path), "w") as output:
        stream = output.add_stream(codec, rate=48_000)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            numpy.full((1, 4800), 5000, dtype=numpy.int16), format="s16", layout="mono"
        )
        frame.sample_rate = 48_000
        output.mux(stream.encode(frame))
        output.mux(stream.encode(None))

    samples = decode_audio(path)
    assert samples.ndim == 1
    assert samples.size == pytest.approx(1600, abs=32)
    assert samples.dtype == numpy.float32
    assert 0.1 < float(samples.max()) < 0.4


def test_validate_model_path_empty_and_missing(tmp_path: Path):
    """Empty or missing directories must be reported as invalid."""
    empty_res = validate_model_path("")
    assert not empty_res["valid"]
    assert "empty" in empty_res["error"].lower()

    non_existent = validate_model_path(str(tmp_path / "does_not_exist"))
    assert not non_existent["valid"]
    assert "does not exist" in non_existent["error"].lower()

    # Directory without required files
    empty_dir = tmp_path / "empty_model"
    empty_dir.mkdir()
    res = validate_model_path(str(empty_dir))
    assert not res["valid"]
    assert "missing" in res["error"].lower()
    assert "config.json" in res["missing_files"]
    assert "model.bin" in res["missing_files"]


def test_default_model_path_is_user_selected(tmp_path: Path, monkeypatch):
    """No machine-specific model path is hard-coded; the desktop launcher supplies one."""
    model = tmp_path / "faster-whisper-large-v3"
    model.mkdir()
    monkeypatch.setenv("SIMILIA_SPEECH_MODEL_PATH", str(model))
    assert get_default_model_path() == str(model)

    monkeypatch.setenv("SIMILIA_SPEECH_MODEL_PATH", "")
    assert get_default_model_path() == ""


def test_frozen_worker_reuses_backend_executable(monkeypatch):
    """A packaged backend must not look for a development virtual environment."""
    import sys

    from app.services.speech.faster_whisper_engine import FasterWhisperEngine

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    engine = FasterWhisperEngine("C:/does/not/exist/python.exe")
    assert engine._worker_command() == [sys.executable, "--speech-worker"]


def test_config_persistence_and_defaults(tmp_path: Path, monkeypatch):
    """Configuration must load defaults and persist correctly to disk."""
    config_file = tmp_path / "speech_test_config.json"
    monkeypatch.setenv("SIMILIA_SPEECH_CONFIG_PATH", str(config_file))

    settings = load_speech_settings()
    assert settings.enabled is True
    assert settings.engine == "faster-whisper"
    assert settings.idle_timeout_seconds == 600

    # Modify and save
    settings.idle_timeout_seconds = 300
    settings.default_language = "ur"
    settings.device = "cpu"
    save_speech_settings(settings)

    reloaded = load_speech_settings()
    assert reloaded.idle_timeout_seconds == 300
    assert reloaded.default_language == "ur"
    assert reloaded.device == "cpu"


def test_legacy_path_migrates_only_when_speech_file_has_no_path(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "speech-settings.json"
    legacy_model = tmp_path / "Legacy Model — اردو"
    legacy_model.mkdir()
    monkeypatch.setenv("SIMILIA_SPEECH_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("SIMILIA_SPEECH_MODEL_PATH", str(legacy_model))
    save_speech_settings(SpeechSettingsModel(default_language="ur"))
    assert load_speech_settings().model_path == str(legacy_model)
    monkeypatch.setenv("SIMILIA_SPEECH_MODEL_PATH", "")
    assert load_speech_settings().model_path == str(legacy_model)
    monkeypatch.setenv("SIMILIA_SPEECH_MODEL_PATH", str(tmp_path))
    assert load_speech_settings().model_path == str(legacy_model)
    assert load_speech_settings().default_language == "ur"


def test_reading_corrupt_speech_file_does_not_overwrite_it(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "speech-settings.json"
    monkeypatch.setenv("SIMILIA_SPEECH_CONFIG_PATH", str(config_file))
    monkeypatch.delenv("SIMILIA_SPEECH_MODEL_PATH", raising=False)
    config_file.write_text('{"model_path":', encoding="utf-8")
    assert load_speech_settings().model_path == ""
    assert config_file.read_text(encoding="utf-8") == '{"model_path":'


def test_speech_manager_idle_timer_and_status(tmp_path: Path):
    """SpeechManager must manage idle countdown and state transitions."""
    settings = SpeechSettingsModel(
        enabled=True,
        engine="faster-whisper",
        model_path=str(tmp_path),
        device="cpu",
        compute_type="int8",
        idle_timeout_seconds=600,
        default_language="auto",
    )
    manager = SpeechManager(settings=settings)
    try:
        status = manager.get_status()
        assert status.status == "unloaded"
        assert status.idle_seconds_remaining is None
        assert status.idle_timeout_seconds == 600

        # Simulate model ready state
        manager._status = "ready"
        manager._last_active_time = time.time()
        with patch.object(manager, "is_loaded", return_value=True):
            status = manager.get_status()
            assert status.status == "ready"
            assert status.idle_seconds_remaining is not None
            assert 590 <= status.idle_seconds_remaining <= 600
    finally:
        manager.shutdown()


def test_speech_manager_idle_timeout_trigger(tmp_path: Path):
    """When idle elapsed time exceeds idle_timeout_seconds, manager auto-unloads."""
    settings = SpeechSettingsModel(
        enabled=True,
        engine="faster-whisper",
        model_path=str(tmp_path),
        device="cpu",
        compute_type="int8",
        idle_timeout_seconds=1,  # Short timeout for test
        default_language="auto",
    )
    manager = SpeechManager(settings=settings)
    try:
        manager._status = "ready"
        manager._engine = MagicMock()
        manager._engine.is_loaded.return_value = True
        # Set last active time to 2 seconds ago
        manager._last_active_time = time.time() - 2.0

        # Wait for idle loop check
        time.sleep(2.5)

        assert manager._status == "unloaded"
        assert manager._last_active_time is None
    finally:
        manager.shutdown()


def test_speech_manager_concurrency_guard(tmp_path: Path):
    """Model must never unload while transcription is actively in progress."""
    settings = SpeechSettingsModel(
        enabled=True,
        idle_timeout_seconds=1,
    )
    manager = SpeechManager(settings=settings)
    try:
        manager._status = "transcribing"
        manager._active_transcriptions = 1
        manager._engine = MagicMock()

        # Call unload while active
        manager.unload()

        # Engine terminate must NOT have been called because active_transcriptions > 0
        manager._engine.terminate.assert_not_called()
        assert manager._active_transcriptions == 1
    finally:
        manager._active_transcriptions = 0
        manager.shutdown()


@pytest.fixture
def client_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with practitioner authentication overridden."""
    monkeypatch.setenv("SIMILIA_SPEECH_CONFIG_PATH", str(tmp_path / "speech-settings.json"))
    monkeypatch.setenv("SIMILIA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SIMILIA_SPEECH_MODEL_PATH", raising=False)
    monkeypatch.setattr(speech_manager, "_speech_manager_instance", None)
    app = create_app()
    app.dependency_overrides[require_practitioner] = lambda: "test-practitioner-123"
    yield TestClient(app)
    if speech_manager._speech_manager_instance is not None:
        speech_manager._speech_manager_instance.shutdown()


def test_api_get_settings(client_env):
    """GET /api/speech/settings returns current configuration and status."""
    res = client_env.get("/api/speech/settings")
    assert res.status_code == 200
    data = res.json()
    assert "settings" in data
    assert "status" in data
    assert data["settings"]["engine"] == "faster-whisper"
    assert "idle_timeout_seconds" in data["settings"]
    assert data["status"]["status"] in ["unloaded", "loading", "ready", "error"]


def test_api_put_settings(client_env):
    """PUT /api/speech/settings updates settings and returns updated state."""
    current = client_env.get("/api/speech/settings").json()["settings"]
    current["idle_timeout_seconds"] = 450
    current["default_language"] = "ur"

    res = client_env.put("/api/speech/settings", json=current)
    assert res.status_code == 200
    data = res.json()
    assert data["settings"]["idle_timeout_seconds"] == 450
    assert data["settings"]["default_language"] == "ur"


def test_api_validate_endpoint(client_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """POST /api/speech/validate reports missing files for empty folder."""
    engine = MagicMock()
    engine.validate_model.side_effect = lambda directory: ModelValidationResult(
        **validate_model_path(str(directory))
    )
    monkeypatch.setattr(get_speech_manager(), "_engine", engine)
    res = client_env.post("/api/speech/validate", json={"model_path": str(tmp_path)})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert "model.bin" in data["missing_files"]


def test_api_save_reloads_unicode_path_and_uses_it_after_restart(
    client_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Models library — اردو"
    folder.mkdir()
    path = str(folder)
    assert client_env.post("/api/speech/load").json()["detail"].endswith(
        "save Speech Settings before loading."
    )
    assert client_env.put("/api/speech/settings", json={"model_path": path}).status_code == 200
    language_update = client_env.put("/api/speech/settings", json={"default_language": "ur"})
    assert language_update.status_code == 200
    assert client_env.put("/api/speech/settings", json={"model_path": ""}).status_code == 422
    assert client_env.get("/api/speech/settings").json()["settings"]["model_path"] == path
    disk_settings = json.loads((tmp_path / "speech-settings.json").read_text(encoding="utf-8"))
    assert disk_settings["model_path"] == path
    get_speech_manager().shutdown()
    monkeypatch.setattr(speech_manager, "_speech_manager_instance", None)
    restarted = get_speech_manager()
    engine = MagicMock()
    monkeypatch.setattr(restarted, "_engine", engine)
    assert client_env.post("/api/speech/load").status_code == 200
    engine.load.assert_called_once_with(model_path=folder, device="auto", compute_type="auto")
    assert restarted.get_settings().default_language == "ur"


def test_failed_atomic_save_keeps_previous_disk_and_runtime_path(
    client_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial_save = client_env.put("/api/speech/settings", json={"model_path": str(tmp_path)})
    assert initial_save.status_code == 200
    replacement = tmp_path / "Replacement"
    replacement.mkdir()

    def fail_replace(*_args: object) -> None:
        raise OSError("mocked write failure")

    with monkeypatch.context() as write_failure:
        write_failure.setattr("app.services.speech.config.os.replace", fail_replace)
        res = client_env.put("/api/speech/settings", json={"model_path": str(replacement)})
    assert res.status_code == 503
    assert "Could not save" in res.json()["detail"]
    assert not list(tmp_path.glob("*.tmp"))
    assert load_speech_settings().model_path == str(tmp_path)
    assert get_speech_manager().get_settings().model_path == str(tmp_path)


def test_load_and_partial_save_use_path_written_after_manager_start(
    client_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = get_speech_manager()
    assert manager.get_settings().model_path == ""
    engine = MagicMock()
    monkeypatch.setattr(manager, "_get_engine", lambda: engine)
    save_speech_settings(SpeechSettingsModel(model_path=str(tmp_path), device="cpu"))
    assert client_env.get("/api/speech/settings").json()["settings"]["model_path"] == str(tmp_path)
    assert client_env.post("/api/speech/load").status_code == 200
    engine.load.assert_called_once_with(model_path=tmp_path, device="cpu", compute_type="auto")
    replacement = tmp_path / "New Model"
    replacement.mkdir()
    save_speech_settings(SpeechSettingsModel(model_path=str(replacement)))
    update = client_env.put("/api/speech/settings", json={"enabled": False})
    assert update.status_code == 200
    assert load_speech_settings().model_path == str(replacement)


def test_api_unload_endpoint(client_env):
    """POST /api/speech/unload cleanly unloads the engine and returns status."""
    res = client_env.post("/api/speech/unload")
    assert res.status_code == 200
    data = res.json()
    assert data["status"]["status"] == "unloaded"


def test_api_transcribe_empty_file_rejected(client_env):
    """POST /api/speech/transcribe rejects empty audio files with 422."""
    res = client_env.post(
        "/api/speech/transcribe",
        files={"audio": ("empty.webm", b"", "audio/webm")},
    )
    assert res.status_code == 422
    assert "empty" in res.json()["detail"].lower()


def test_api_transcribe_with_mock_engine(client_env, tmp_path: Path):
    """POST /api/speech/transcribe returns expected transcription results."""
    manager = get_speech_manager()
    fake_result = TranscriptionResult(
        text="Patient complains of eczema and skin itching",
        language="en",
        language_probability=0.98,
        duration_seconds=3.2,
        segments=[
            TranscriptionSegment(
                id=0,
                start=0.0,
                end=3.2,
                text="Patient complains of eczema and skin itching",
            )
        ],
    )

    with patch.object(manager, "transcribe", return_value=fake_result):
        res = client_env.post(
            "/api/speech/transcribe",
            files={"audio": ("test.webm", b"RIFF....WAVEfmt ....", "audio/webm")},
            data={"language": "en"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["text"] == "Patient complains of eczema and skin itching"
        assert data["language"] == "en"
        assert len(data["segments"]) == 1
