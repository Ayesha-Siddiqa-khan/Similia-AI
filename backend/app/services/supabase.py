"""Supabase connectivity for FastAPI.

Uses the anon/publishable key by default; the secret (service-role) key is read
from settings but must only ever be used server-side, never returned to clients.
"""

from functools import lru_cache

from supabase import Client

from app.core.config import Settings, get_settings


@lru_cache
def get_supabase_client() -> Client:
    """Lazily create the Supabase client (publishable key).

    Raises a clear error when unconfigured instead of failing at import time,
    so the app boots before credentials exist (Phase 1).
    """
    settings: Settings = get_settings()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_PUBLISHABLE_KEY in .env (see .env.example)."
        )
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_publishable_key)


@lru_cache
def get_supabase_admin_client() -> Client:
    """Service-role client for trusted backend knowledge-base operations.

    RLS is deny-by-default on every knowledge_* table (no anon/authenticated
    policies), so all ingestion writes and search RPCs require this client.
    The secret key must never leave the server.
    """
    settings: Settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError(
            "Knowledge-base operations require the service-role key. Set "
            "SUPABASE_URL and SUPABASE_SECRET_KEY in .env (see .env.example)."
        )
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_secret_key)
