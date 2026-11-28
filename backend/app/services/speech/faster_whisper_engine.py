"""FasterWhisper implementation of SpeechEngine using an isolated worker process."""

import json
import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import psutil

from app.services.speech.base import (
    ModelValidationResult,
    SpeechEngine,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)

WORKER_SCRIPT = Path(__file__).resolve().parent / "worker.py"


class FasterWhisperEngine(SpeechEngine):
    """Faster-Whisper engine running in a dedicated isolated worker subprocess.

    This ensures complete OS memory reclamation upon idle unloading or shutdown.
    """

    def __init__(self, python_executable: str | None = None):
        self._python_executable = python_executable or "python"
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._loaded = False
        self._current_model_path: str | None = None
        self._current_device: str = "auto"
        self._current_compute_type: str = "auto"

    def _worker_command(self) -> list[str]:
        """Command that starts the worker in a frozen build or the dev interpreter.

        A packaged backend re-uses its own executable with --speech-worker, so the
        installed app never needs a system Python or the development venv.
        """
        if getattr(sys, "frozen", False):
            return [sys.executable, "--speech-worker"]
        python = self._python_executable or ""
        if python and Path(python).is_file():
            return [python, str(WORKER_SCRIPT)]
        return [sys.executable, str(WORKER_SCRIPT)]

    def _ensure_worker(self) -> subprocess.Popen[str]:
        """Ensure the background worker subprocess is running."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self._process

            # Start worker subprocess
            cmd = self._worker_command()
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )
            except Exception as exc:
                logger.error(f"Failed to start speech worker process with {cmd}: {exc}")
                raise RuntimeError(
                    f"Could not start speech worker with Python '{self._python_executable}': {exc}"
                ) from exc

            assert self._process.stdout is not None
            responses = self._responses = queue.Queue()
            stdout = self._process.stdout

            def read_responses() -> None:
                try:
                    for line in stdout:
                        responses.put(line)
                finally:
                    responses.put("")
                    stdout.close()

            threading.Thread(target=read_responses, daemon=True).start()
            logger.info("Started speech worker pid=%d", self._process.pid)

            # Verify worker starts with ping. A frozen executable can take longer to boot.
            try:
                resp = self._send_command_unlocked(
                    {"cmd": "ping", "check_runtime": bool(getattr(sys, "frozen", False))},
                    timeout=60 if getattr(sys, "frozen", False) else 30,
                )
                if resp.get("status") != "ok":
                    raise RuntimeError(f"Unexpected ping response: {resp}")
            except Exception as exc:
                self._kill_worker_unlocked()
                raise RuntimeError(f"Speech worker failed health check: {exc}") from exc

            return self._process

    def _send_command_unlocked(self, cmd: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        """Send command to worker and receive JSON response without holding outer lock."""
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("Speech worker process is not running.")

        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        try:
            assert self._process.stdin is not None
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            logger.error(f"Broken pipe communicating with speech worker: {exc}")
            self._kill_worker_unlocked()
            raise RuntimeError(f"Speech worker process pipe broken: {exc}") from exc

        try:
            resp_line = self._responses.get(timeout=timeout)
        except queue.Empty:
            self._kill_worker_unlocked()
            raise RuntimeError(f"Speech worker timed out during {cmd['cmd']}.") from None
        if not resp_line:
            self._kill_worker_unlocked()
            raise RuntimeError("Speech worker terminated unexpectedly.")

        try:
            return json.loads(resp_line.strip())
        except json.JSONDecodeError:
            self._kill_worker_unlocked()
            raise RuntimeError("Invalid response from speech worker.") from None

    def _kill_worker_unlocked(self) -> None:
        """Forcefully kill worker subprocess if active."""
        if self._process is not None:
            try:
                if self._process.poll() is None:
                    self._process.kill()
                    self._process.wait(timeout=3)
            except Exception as exc:
                logger.warning(f"Error terminating worker process: {exc}")
            finally:
                if self._process.stdin is not None:
                    self._process.stdin.close()
                self._process = None
                self._loaded = False

    def validate_model(self, model_path: Path) -> ModelValidationResult:
        """Validate candidate model directory using the worker."""
        self._ensure_worker()
        with self._lock:
            resp = self._send_command_unlocked(
                {"cmd": "validate", "model_path": str(model_path.resolve())}
            )
            if resp.get("status") != "ok":
                return ModelValidationResult(
                    valid=False,
                    error=resp.get("error", "Unknown validation error"),
                    model_path=str(model_path),
                )
            result_data = resp.get("result", {})
            return ModelValidationResult(**result_data)

    def load(self, model_path: Path, device: str = "auto", compute_type: str = "auto") -> None:
        """Load Faster-Whisper model into memory."""
        self._ensure_worker()
        with self._lock:
            resp = self._send_command_unlocked(
                {
                    "cmd": "load",
                    "model_path": str(model_path.resolve()),
                    "device": device,
                    "compute_type": compute_type,
                },
                timeout=180.0,
            )
            if resp.get("status") != "ok":
                raise RuntimeError(
                    f"Failed to load speech model: {resp.get('error', 'Unknown error')}"
                )
            res = resp.get("result", {})
            self._loaded = bool(res.get("loaded", True))
            self._current_model_path = res.get("model_path")
            self._current_device = res.get("device", device)
            self._current_compute_type = res.get("compute_type", compute_type)

    def unload(self) -> None:
        """Unload model from memory within the worker."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._send_command_unlocked({"cmd": "unload"}, timeout=10.0)
                except Exception as exc:
                    logger.warning(f"Error sending unload command to worker: {exc}")
            self._loaded = False
            self._current_model_path = None

    def terminate(self) -> None:
        """Terminate the worker subprocess completely to release 100% of RAM/VRAM."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._send_command_unlocked({"cmd": "exit"}, timeout=5.0)
                    self._process.wait(timeout=3)
                except Exception:
                    pass
            self._kill_worker_unlocked()

    def is_loaded(self) -> bool:
        """Check if model is currently loaded."""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._loaded = False
                return False
            return self._loaded

    def get_memory_rss_mb(self) -> float | None:
        """Get resident set size (RAM) of worker process in MB."""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return 0.0
            try:
                p = psutil.Process(self._process.pid)
                return round(p.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                return None

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        task: str = "transcribe",
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file using the loaded model."""
        if not self.is_loaded():
            raise RuntimeError("Model is not loaded. Load model before calling transcribe.")

        with self._lock:
            resp = self._send_command_unlocked(
                {
                    "cmd": "transcribe",
                    "audio_path": str(audio_path.resolve()),
                    "language": language,
                    "task": task,
                    "initial_prompt": initial_prompt,
                },
                timeout=300.0,
            )
            if resp.get("status") != "ok":
                raise RuntimeError(
                    f"Transcription failed: {resp.get('error', 'Unknown transcription error')}"
                )

            res = resp.get("result", {})
            segments = [
                TranscriptionSegment(
                    id=s["id"],
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                )
                for s in res.get("segments", [])
            ]
            return TranscriptionResult(
                text=res.get("text", ""),
                language=res.get("language"),
                language_probability=res.get("language_probability"),
                duration_seconds=res.get("duration_seconds", 0.0),
                segments=segments,
            )
