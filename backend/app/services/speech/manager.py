"""SpeechManager: singleton managing model lifecycle and idle unloading timer."""

import logging
import threading
import time
from pathlib import Path

from app.services.speech.base import (
    EngineStatus,
    ModelValidationResult,
    SpeechSettingsModel,
    TranscriptionResult,
)
from app.services.speech.config import (
    load_speech_settings,
    read_speech_settings,
    save_speech_settings,
)
from app.services.speech.faster_whisper_engine import FasterWhisperEngine

logger = logging.getLogger(__name__)

_speech_manager_instance: "SpeechManager | None" = None
_manager_lock = threading.Lock()


class SpeechManager:
    """Central coordinator for pluggable speech engines and on-demand model lifecycle."""

    def __init__(self, settings: SpeechSettingsModel | None = None):
        self._settings = settings or load_speech_settings()
        self._file_backed = settings is None
        self._lock = threading.RLock()
        self._engine: FasterWhisperEngine | None = None
        self._status: str = "unloaded"  # unloaded | loading | ready | transcribing | error
        self._error_message: str | None = None
        self._last_active_time: float | None = None
        self._active_transcriptions: int = 0
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

        self._start_monitor()

    def _start_monitor(self) -> None:
        """Start background monitor thread for idle unloading."""
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._idle_monitor_loop,
                name="SpeechIdleMonitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def _idle_monitor_loop(self) -> None:
        """Periodic loop checking for model inactivity and auto-unloading after idle timeout."""
        logger.info("Speech idle monitor started.")
        while not self._stop_event.is_set():
            # Check every 2 seconds
            if self._stop_event.wait(timeout=2.0):
                break

            with self._lock:
                if (
                    self._status == "ready"
                    and self._engine is not None
                    and self._engine.is_loaded()
                    and self._active_transcriptions == 0
                    and self._last_active_time is not None
                ):
                    elapsed = time.time() - self._last_active_time
                    timeout = self._settings.idle_timeout_seconds
                    if elapsed >= timeout:
                        logger.info(
                            f"Speech model idle for {round(elapsed, 1)}s (timeout={timeout}s). "
                            "Unloading model and freeing memory."
                        )
                        self._unload_internal(reason="idle_timeout")

    def _get_engine(self) -> FasterWhisperEngine:
        """Get or initialize the speech engine."""
        if self._engine is None:
            self._engine = FasterWhisperEngine(
                python_executable=self._settings.python_executable or None
            )
        return self._engine

    def get_settings(self) -> SpeechSettingsModel:
        """Return the saved settings, independently of the running engine's status."""
        with self._lock:
            return self._saved_settings().model_copy()

    def _saved_settings(self) -> SpeechSettingsModel:
        if self._file_backed:
            try:
                saved = read_speech_settings()
                if not saved.model_path.strip():
                    saved.model_path = self._settings.model_path
                return saved
            except (OSError, ValueError):
                pass
        return self._settings

    @staticmethod
    def _runtime_settings(settings: SpeechSettingsModel) -> tuple[str, str, str]:
        return settings.model_path, settings.device, settings.compute_type

    def update_settings(self, new_settings: SpeechSettingsModel) -> SpeechSettingsModel:
        """Update speech settings and persist them."""
        with self._lock:
            changes = new_settings.model_dump(exclude_unset=True, exclude={"python_executable"})
            if "model_path" in changes:
                changes["model_path"] = changes["model_path"].strip()
            saved = self._saved_settings()
            new_settings = saved.model_copy(update=changes)
            if new_settings.model_path != saved.model_path:
                model_dir = Path(new_settings.model_path)
                if not model_dir.is_absolute() or not model_dir.is_dir():
                    raise ValueError("Choose an existing absolute model folder before saving.")
            runtime_changed = self._runtime_settings(new_settings) != self._runtime_settings(
                self._settings
            )
            if runtime_changed and self._active_transcriptions:
                raise ValueError("Wait for transcription to finish before changing the model.")

            save_speech_settings(new_settings)
            self._settings = new_settings
            if runtime_changed and self.is_loaded():
                self._unload_internal(reason="settings_changed")
            return self._settings.model_copy()

    def validate_model_path(self, path_str: str) -> ModelValidationResult:
        """Validate candidate model directory."""
        if not path_str or not path_str.strip():
            return ModelValidationResult(
                valid=False,
                error="Model path is required.",
                model_path="",
            )

        p = Path(path_str.strip())
        engine = self._get_engine()
        return engine.validate_model(p)

    def is_loaded(self) -> bool:
        """Whether model is currently loaded in memory."""
        with self._lock:
            return self._engine is not None and self._engine.is_loaded()

    def load_model(self) -> None:
        """Explicitly or on-demand load the configured model."""
        with self._lock:
            saved = self._saved_settings()
            if not saved.model_path.strip():
                raise ValueError("Choose a model folder and save Speech Settings before loading.")

            p = Path(saved.model_path)
            if not p.is_dir():
                raise FileNotFoundError("The saved model folder is unavailable. Check Settings.")
            if self._active_transcriptions:
                raise ValueError("Wait for transcription to finish before loading the model.")
            if self._runtime_settings(saved) != self._runtime_settings(self._settings):
                self._unload_internal(reason="settings_changed")
            self._settings = saved

            self._status = "loading"
            self._error_message = None

            try:
                engine = self._get_engine()
                engine.load(
                    model_path=p,
                    device=self._settings.device,
                    compute_type=self._settings.compute_type,
                )
                self._status = "ready"
                self._last_active_time = time.time()
                logger.info("Speech model loaded successfully.")
            except Exception as exc:
                self._status = "error"
                self._error_message = str(exc)
                logger.error("Speech model load failed (%s).", type(exc).__name__)
                raise

    def unload(self) -> None:
        """Unload the speech model immediately and release all OS memory."""
        with self._lock:
            self._unload_internal(reason="manual")

    def _unload_internal(self, reason: str = "manual") -> None:
        """Internal unload routine that completely terminates worker process."""
        if self._active_transcriptions > 0:
            logger.warning(f"Unload requested ({reason}) but transcription is active. Deferring.")
            return

        logger.info(f"Unloading speech model (reason={reason})...")
        if self._engine is not None:
            self._engine.terminate()
            self._engine = None

        self._status = "unloaded"
        self._last_active_time = None
        self._error_message = None

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        task: str = "transcribe",
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file, loading the model on-demand and resetting idle timer."""
        # Check settings
        with self._lock:
            if not self._settings.enabled:
                raise RuntimeError("Local speech recognition is disabled in settings.")

            # Lazy on-demand loading if not already loaded
            if not self.is_loaded():
                logger.info("Transcription requested but model is not loaded. Loading on demand...")
                self.load_model()

            self._status = "transcribing"
            self._active_transcriptions += 1
            self._last_active_time = time.time()

        start_time = time.time()
        try:
            target_lang = language or self._settings.default_language
            if target_lang in ("auto", "", None):
                target_lang = None

            result = self._engine.transcribe(
                audio_path=audio_path,
                language=target_lang,
                task=task,
                initial_prompt=initial_prompt,
            )
            return result
        finally:
            with self._lock:
                self._active_transcriptions = max(0, self._active_transcriptions - 1)
                self._last_active_time = time.time()
                self._status = "ready"
                logger.info(
                    f"Transcription finished in {round(time.time() - start_time, 2)}s. "
                    f"Idle timer reset to {self._settings.idle_timeout_seconds}s."
                )

    def get_status(self) -> EngineStatus:
        """Inspect current operational status and idle time."""
        with self._lock:
            remaining_seconds: int | None = None
            if self._status == "transcribing":
                remaining_seconds = self._settings.idle_timeout_seconds
            elif (
                self._status == "ready"
                and self._last_active_time is not None
                and self.is_loaded()
            ):
                elapsed = time.time() - self._last_active_time
                remaining_seconds = max(0, int(self._settings.idle_timeout_seconds - elapsed))

            memory_mb = None
            if self._engine is not None:
                memory_mb = self._engine.get_memory_rss_mb()

            return EngineStatus(
                status=self._status,
                engine=self._settings.engine,
                model_path=self._settings.model_path or None,
                device=self._settings.device,
                compute_type=self._settings.compute_type,
                idle_seconds_remaining=remaining_seconds,
                idle_timeout_seconds=self._settings.idle_timeout_seconds,
                memory_rss_mb=memory_mb,
                last_active_timestamp=self._last_active_time,
                error_message=self._error_message,
                python_executable=self._settings.python_executable or None,
            )

    def shutdown(self) -> None:
        """Clean up background threads and child processes on server shutdown."""
        logger.info("Shutting down SpeechManager...")
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        self.unload()


def get_speech_manager() -> SpeechManager:
    """Return singleton SpeechManager."""
    global _speech_manager_instance
    with _manager_lock:
        if _speech_manager_instance is None:
            _speech_manager_instance = SpeechManager()
        return _speech_manager_instance
