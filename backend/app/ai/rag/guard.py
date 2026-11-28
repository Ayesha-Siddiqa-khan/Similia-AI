"""Shared guard: stop spending embedding quota while the provider stop is set.

The stop is the database flag `system_flags.provider_pause`. It survives restarts and is shared
by every server, and only the owner clears it (SQL editor). If the database is configured but
cannot be read, the guard answers "paused": it must never allow paid calls on a guess.
The command-line pipeline's old manifest file is only consulted when no database is configured
at all (a bare local run); the app otherwise ignores it.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0
FLAG = "provider_pause"
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _read_db_flag() -> dict[str, Any] | None | bool:
    """The flag row, None when the database is not configured, False when it cannot be read."""
    from app.core.config import get_settings
    from app.services import knowledge_db
    from app.services.supabase import get_supabase_admin_client

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        return None
    try:
        row = knowledge_db.get_system_flag(get_supabase_admin_client(), FLAG)
        return row if row is not None else {"paused": False}  # no row: nothing ever set a stop
    except Exception as exc:  # unreadable (network, or the migration is not applied yet)
        logger.warning("Provider stop unreadable (%s). Holding embeddings.", type(exc).__name__)
        return False


def _db_state() -> dict[str, Any] | None | bool:
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    value = _read_db_flag()
    _cache.update(at=now, value=value if value is not None else "unconfigured")
    return value


def reset_cache() -> None:
    _cache.update(at=0.0, value=None)


def pause_reason() -> str | None:
    """Why the provider stop is set, or None when embedding may proceed."""
    from app.ai.ingestion.local import REPORTS, read_json

    state = _db_state()
    if state is False:
        return "The provider stop cannot be read from the database, so embedding is held."
    if isinstance(state, dict):
        if state.get("paused"):
            return state.get("reason") or "The provider stop is set in the database."
        return None
    if state is None or state == "unconfigured":
        manifest = REPORTS / "run_manifest.json"
        if manifest.exists() and read_json(manifest).get("status") == "stopped_provider_http_429":
            return "The last command-line run ended on a provider HTTP 429."
        return None
    return None


def embedding_paused() -> bool:
    """True while the provider stop is set (see module docstring)."""
    return pause_reason() is not None
