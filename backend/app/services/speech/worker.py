"""Isolated worker process for local Faster-Whisper inference.

This script runs in an isolated Python subprocess communicating via single-line JSON IPC
over stdin/stdout. It keeps all CTranslate2 and PyTorch memory allocations strictly isolated
from the main web server process so terminating this worker completely frees all RAM/VRAM.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# Force UTF-8 encoding for standard I/O streams (vital for Urdu script).
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_loaded_model = None
_loaded_model_path = None
_loaded_device = None
_loaded_compute_type = None


def send_response(data: dict) -> None:
    """Send a single-line JSON response to stdout."""
    line = json.dumps(data, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def log_debug(message: str) -> None:
    """Write debug output to stderr so stdout JSON is not corrupted."""
    sys.stderr.write(f"[speech_worker] {message}\n")
    sys.stderr.flush()


def validate_model_path(path_str: str) -> dict:
    """Inspect the given directory path to verify CTranslate2 Faster-Whisper weights."""
    if not path_str or not path_str.strip():
        return {
            "valid": False,
            "error": "Model path is empty.",
            "files_found": [],
            "missing_files": ["model.bin", "config.json"],
        }

    p = Path(path_str.strip())
    if not p.exists():
        return {
            "valid": False,
            "error": f"Directory does not exist: {p}",
            "files_found": [],
            "missing_files": ["model.bin", "config.json"],
        }
    if not p.is_dir():
        return {
            "valid": False,
            "error": f"Path is not a directory: {p}",
            "files_found": [],
            "missing_files": [],
        }

    found = [f.name for f in p.iterdir() if f.is_file()]
    has_weights = "model.bin" in found
    # Faster-Whisper otherwise tries to fetch a fallback tokenizer from Hugging Face.
    has_tokenizer = "tokenizer.json" in found

    missing = []
    if "config.json" not in found:
        missing.append("config.json")
    if not has_weights:
        missing.append("model.bin")
    if not has_tokenizer:
        missing.append("tokenizer.json")

    total_size = sum(f.stat().st_size for f in p.iterdir() if f.is_file())
    size_mb = round(total_size / (1024 * 1024), 2)

    if missing:
        return {
            "valid": False,
            "error": f"Missing required model files: {', '.join(missing)}",
            "files_found": found,
            "missing_files": missing,
            "size_bytes": total_size,
            "size_mb": size_mb,
            "model_path": str(p.resolve()),
        }

    # Inspect config.json for model architecture details
    model_type = "faster-whisper"
    architecture = "whisper"
    try:
        config_path = p / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if "model_type" in cfg:
                model_type = cfg["model_type"]
            if "_name_or_path" in cfg:
                architecture = cfg["_name_or_path"]
    except Exception as e:
        log_debug(f"Warning reading config.json: {e}")

    return {
        "valid": True,
        "error": None,
        "engine": "faster-whisper",
        "model_type": model_type,
        "architecture": architecture,
        "model_path": str(p.resolve()),
        "size_bytes": total_size,
        "size_mb": size_mb,
        "files_found": found,
        "missing_files": [],
    }


def detect_optimal_device() -> tuple[str, str]:
    """Detect available accelerator and optimal compute type."""
    try:
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
        if cuda_count > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def load_model(path_str: str, device: str = "auto", compute_type: str = "auto") -> dict:
    """Load FasterWhisper model into memory."""
    global _loaded_model, _loaded_model_path, _loaded_device, _loaded_compute_type

    val = validate_model_path(path_str)
    if not val["valid"]:
        raise ValueError(val["error"])

    # Resolve device and compute_type
    target_device = device.lower() if device else "auto"
    target_compute = compute_type.lower() if compute_type else "auto"

    if target_device == "auto":
        # A Windows driver alone does not supply the CUDA libraries used by CTranslate2.
        target_device = "cpu" if getattr(sys, "frozen", False) else detect_optimal_device()[0]
    if target_compute == "auto":
        target_compute = "float16" if target_device == "cuda" else "int8"

    log_debug(f"Loading WhisperModel from {path_str} on {target_device} ({target_compute})...")

    from faster_whisper import WhisperModel

    cpu_threads = min(8, max(1, os.cpu_count() or 4))
    model = WhisperModel(
        model_size_or_path=str(Path(path_str.strip()).resolve()),
        device=target_device,
        compute_type=target_compute,
        cpu_threads=cpu_threads,
        num_workers=1,
        local_files_only=True,
    )

    _loaded_model = model
    _loaded_model_path = str(Path(path_str.strip()).resolve())
    _loaded_device = target_device
    _loaded_compute_type = target_compute

    log_debug("Model loaded successfully.")
    return {
        "loaded": True,
        "model_path": _loaded_model_path,
        "device": _loaded_device,
        "compute_type": _loaded_compute_type,
    }


def unload_model() -> None:
    """Unload model and collect garbage."""
    global _loaded_model, _loaded_model_path, _loaded_device, _loaded_compute_type
    _loaded_model = None
    _loaded_model_path = None
    _loaded_device = None
    _loaded_compute_type = None
    gc.collect()
    log_debug("Model unloaded from memory.")


def decode_audio(path: Path) -> NDArray[np.float32]:
    """Decode mono 16 kHz samples through the bundled PyAV runtime."""
    import av
    import numpy as np

    # Faster-Whisper 1.2.1's file decoder passes a keyword removed by PyAV 19.
    # Passing samples directly also uses the same decoder for browser WebM and WAV.
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=16_000)
    chunks = []
    with av.open(str(path), mode="r") as container:
        for frame in container.decode(audio=0):
            frame.pts = None
            chunks.extend(output.to_ndarray().reshape(-1) for output in resampler.resample(frame))
        chunks.extend(output.to_ndarray().reshape(-1) for output in resampler.resample(None))
    if not chunks:
        raise ValueError("The recording contains no audio samples.")
    return np.concatenate(chunks)


def transcribe_audio(
    audio_path: str,
    language: str | None = None,
    task: str = "transcribe",
    initial_prompt: str | None = None,
) -> dict:
    """Transcribe an audio file using the loaded FasterWhisper model."""
    global _loaded_model
    if _loaded_model is None:
        raise RuntimeError("Speech model is not loaded. Load a model before transcribing.")

    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    lang = language.strip().lower() if language and language.strip() not in ("auto", "") else None

    # Common medical/clinical vocabulary prompt for English and Urdu clinical terms
    default_prompt = (
        "Similia homeopathic clinical case consultation. "
        "Symptoms, diagnosis, modalities, Graphites, Sulphur, Natrum muriaticum, "
        "Arnica, Pulsatilla, Lycopodium, Calcarea, Nux vomica, Hepar sulph, "
        "اکزیما، خارش، درد، جلن، کھانسی، بخار، دوا، علامات"
    )
    prompt = f"{default_prompt} {initial_prompt}" if initial_prompt else default_prompt

    log_debug(f"Transcribing audio: {p.name} (language={lang}, task={task})...")

    segments, info = _loaded_model.transcribe(
        decode_audio(p),
        language=lang,
        task=task,
        initial_prompt=prompt,
        beam_size=5,
        word_timestamps=False,
        condition_on_previous_text=False,
    )

    segment_list = []
    text_parts = []
    for seg in segments:
        s_text = seg.text.strip()
        if s_text:
            text_parts.append(s_text)
            segment_list.append(
                {
                    "id": seg.id,
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": s_text,
                }
            )

    full_text = " ".join(text_parts).strip()
    return {
        "text": full_text,
        "language": info.language,
        "language_probability": round(info.language_probability, 3)
        if info.language_probability
        else 1.0,
        "duration_seconds": round(info.duration, 2),
        "segments": segment_list,
    }


def main():
    """Main worker event loop."""
    log_debug("Worker started. Waiting for JSON commands on stdin...")

    while True:
        line = sys.stdin.readline()
        if not line:
            # EOF reached: parent process closed pipe
            log_debug("Stdin closed (EOF). Exiting worker.")
            break

        line = line.strip()
        if not line:
            continue

        try:
            cmd_data = json.loads(line)
            cmd = cmd_data.get("cmd")

            if cmd == "ping":
                if cmd_data.get("check_runtime"):
                    from faster_whisper import WhisperModel

                    if not callable(WhisperModel):
                        raise RuntimeError("Faster-Whisper runtime is unavailable.")
                send_response({"status": "ok", "msg": "pong"})

            elif cmd == "validate":
                res = validate_model_path(cmd_data.get("model_path", ""))
                send_response({"status": "ok", "result": res})

            elif cmd == "load":
                res = load_model(
                    path_str=cmd_data.get("model_path", ""),
                    device=cmd_data.get("device", "auto"),
                    compute_type=cmd_data.get("compute_type", "auto"),
                )
                send_response({"status": "ok", "result": res})

            elif cmd == "transcribe":
                res = transcribe_audio(
                    audio_path=cmd_data.get("audio_path", ""),
                    language=cmd_data.get("language"),
                    task=cmd_data.get("task", "transcribe"),
                    initial_prompt=cmd_data.get("initial_prompt"),
                )
                send_response({"status": "ok", "result": res})

            elif cmd == "unload":
                unload_model()
                send_response({"status": "ok", "unloaded": True})

            elif cmd == "exit":
                log_debug("Exit command received. Cleaning up...")
                unload_model()
                send_response({"status": "ok", "exited": True})
                break

            elif cmd == "status":
                send_response(
                    {
                        "status": "ok",
                        "loaded": _loaded_model is not None,
                        "model_path": _loaded_model_path,
                        "device": _loaded_device,
                        "compute_type": _loaded_compute_type,
                    }
                )

            else:
                send_response({"status": "error", "error": f"Unknown command: {cmd}"})

        except Exception as exc:
            log_debug(f"Error handling command: {exc}\n{traceback.format_exc()}")
            send_response({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    main()
