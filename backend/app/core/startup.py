"""Configuration checks at start-up and the readiness probe.

Nothing here prints or returns a secret: problems name the setting, never its value.
"""

import logging
from collections.abc import Callable
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Production refuses to start with an unsafe or incomplete configuration."""


def is_production(settings: Settings) -> bool:
    return settings.environment.strip().lower() == "production"


def configuration_problems(settings: Settings) -> list[str]:
    """Everything wrong or risky about the settings, as plain sentences."""
    problems: list[str] = []
    if not settings.supabase_url:
        problems.append("SUPABASE_URL is not set.")
    if not settings.supabase_secret_key:
        problems.append("SUPABASE_SECRET_KEY is not set.")
    if not settings.supabase_publishable_key:
        problems.append("SUPABASE_PUBLISHABLE_KEY is not set.")
    if not settings.app_encryption_key:
        problems.append("APP_ENCRYPTION_KEY is not set (doctors' AI keys cannot be stored).")
    else:
        try:
            Fernet(settings.app_encryption_key.encode())
        except (ValueError, TypeError):
            problems.append("APP_ENCRYPTION_KEY is not a valid Fernet key.")
    for older in (settings.app_encryption_key_previous or "").split(","):
        if older.strip():
            try:
                Fernet(older.strip().encode())
            except (ValueError, TypeError):
                problems.append("APP_ENCRYPTION_KEY_PREVIOUS has an invalid key.")
                break
    origins = settings.cors_origins_list
    if not origins:
        problems.append("CORS_ORIGINS is empty.")
    if "*" in origins:
        problems.append("CORS_ORIGINS must list the real site, not '*'.")
    if is_production(settings):
        insecure = [o for o in origins if o.startswith("http://")]
        if insecure:
            problems.append("CORS_ORIGINS has http:// origins; production must use https://.")
        if not settings.voyage_api_key:
            problems.append("VOYAGE_API_KEY is not set (search and analysis cannot run).")
    return problems


def check_configuration(settings: Settings) -> list[str]:
    """Raise in production, warn elsewhere. Returns the problems found."""
    problems = configuration_problems(settings)
    if not problems:
        return problems
    if is_production(settings):
        raise ConfigurationError("Unsafe configuration, refusing to start: " + " ".join(problems))
    for problem in problems:
        logger.warning("Configuration: %s", problem)
    return problems


def readiness(settings: Settings, database_check: Callable[[], Any]) -> tuple[bool, dict[str, str]]:
    """Can this instance serve real requests? Reports 'ok' or a short reason per component."""
    checks: dict[str, str] = {}
    problems = configuration_problems(settings)
    checks["configuration"] = "ok" if not problems else f"{len(problems)} problem(s)"
    try:
        database_check()
        checks["database"] = "ok"
    except Exception:  # the reason may contain connection details: keep it server-side
        logger.exception("Readiness: database check failed")
        checks["database"] = "unavailable"
    return all(value == "ok" for value in checks.values()), checks
