"""Desktop entrypoint for the frozen FastAPI backend.

Two modes share one executable:

* default: run the API with Uvicorn on 127.0.0.1
* ``--speech-worker``: run the isolated Faster-Whisper worker over stdin/stdout

The speech worker is started by ``FasterWhisperEngine`` as a child of this same
executable, so the installed app never depends on a system Python or the
development virtual environment.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import threading
from pathlib import Path


def _prepare_console() -> None:
    """Use UTF-8 for logs and worker JSON (Urdu text must survive)."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass


def _run_api(host: str, port: int) -> None:
    import uvicorn

    from app.main import app

    if host != "127.0.0.1":
        raise ValueError("The desktop backend must bind to 127.0.0.1")
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("SIMILIA_LOG_LEVEL", "info"),
        access_log=False,  # access logs can contain query strings and record ids
        proxy_headers=False,
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    if os.environ.get("SIMILIA_DESKTOP_TOKEN") and sys.stdin is not None:
        # Electron owns the only writer. EOF also releases the backend if Electron crashes.
        def wait_for_launcher() -> None:
            sys.stdin.read()
            server.should_exit = True

        threading.Thread(target=wait_for_launcher, daemon=True).start()
    server.run()


def main() -> None:
    multiprocessing.freeze_support()
    _prepare_console()

    # In a source checkout PyInstaller is not involved; make `app` importable.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    if "--speech-worker" in sys.argv[1:]:
        from app.services.speech.worker import main as worker_main

        worker_main()
        return

    parser = argparse.ArgumentParser(description="Similia AI local backend")
    parser.add_argument("--host", default=os.environ.get("SIMILIA_BACKEND_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("SIMILIA_BACKEND_PORT", "8011"))
    )
    args = parser.parse_args()
    _run_api(args.host, args.port)


if __name__ == "__main__":
    main()
