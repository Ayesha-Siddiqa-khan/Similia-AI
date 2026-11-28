"""Bring-your-own AI key: store, verify and use each practitioner's provider key.

The plaintext key exists only (a) in the request that saves it, (b) briefly in memory when that
user's AI call is made. It is encrypted at rest (see app.core.vault) and never returned by any
endpoint, only its last four characters.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

import httpx

from app.core.vault import VaultError, decrypt_secret
from app.services.compatible_llm import (
    COMPATIBLE_PROVIDERS,
    MODEL_ID_PATTERN,
    CompatibleLLMProvider,
)
from app.services.llm import AnthropicLLMProvider, LLMProvider

PROVIDER = "anthropic"
PROVIDERS = {
    PROVIDER: "Anthropic",
    **{key: value.label for key, value in COMPATIBLE_PROVIDERS.items()},
}
DEFAULT_MODEL = "claude-sonnet-5-5"
ALLOWED_MODELS: dict[str, str] = {
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (recommended: quality and cost balance)",
    "claude-opus-5-5": "Claude Opus 5.5 (most capable, higher cost)",
    "claude-haiku-5-5": "Claude Haiku 5.5 (fastest, lowest cost)",
}


ActiveFor = Literal["1d", "7d", "30d"]
DEFAULT_ACTIVE_FOR: ActiveFor = "1d"
ACTIVE_OPTIONS: dict[str, tuple[str, timedelta]] = {
    "1d": ("1 day (default)", timedelta(days=1)),
    "7d": ("1 week", timedelta(days=7)),
    "30d": ("1 month", timedelta(days=30)),
}


def active_until_from_now(active_for: str, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + ACTIVE_OPTIONS[active_for][1]


def parse_active_until(row: dict[str, Any]) -> datetime | None:
    raw = row.get("active_until")
    if not raw:
        return None
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def is_active(row: dict[str, Any], now: datetime | None = None) -> bool:
    """A saved key is usable only until `active_until`; a missing value counts as paused."""
    until = parse_active_until(row)
    return until is not None and (now or datetime.now(timezone.utc)) < until


class NoUserKeyError(RuntimeError):
    """The practitioner has not saved an AI key yet."""


class KeyPausedError(RuntimeError):
    """A key is saved but its active period has ended."""


class KeyRejectedError(RuntimeError):
    """The provider refused the key."""


class ProviderUnavailableError(RuntimeError):
    """The provider could not be reached to verify the key."""


class UserAIStore(Protocol):
    def get(self, owner: str) -> dict[str, Any] | None: ...
    def save(self, owner: str, row: dict[str, Any]) -> None: ...
    def update(self, owner: str, provider: str, changes: dict[str, Any]) -> bool: ...
    def delete(self, owner: str) -> None: ...


class SupabaseUserAIStore:
    """Owner-scoped persistence on the service-role client (RLS has no client policies)."""

    def __init__(self, client: Any) -> None:
        self._db = client

    def get(self, owner: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("user_ai_settings").select("*").eq("practitioner_id", owner).execute()
        ).data
        return rows[0] if rows else None

    def save(self, owner: str, row: dict[str, Any]) -> None:
        self._db.table("user_ai_settings").upsert(
            {**row, "practitioner_id": owner, "updated_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="practitioner_id",
        ).execute()

    def delete(self, owner: str) -> None:
        self._db.table("user_ai_settings").delete().eq("practitioner_id", owner).execute()

    def update(self, owner: str, provider: str, changes: dict[str, Any]) -> bool:
        result = (
            self._db.table("user_ai_settings")
            .update({**changes, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("practitioner_id", owner)
            .eq("provider", provider)
            .execute()
        )
        return bool(result.data)


def verify_anthropic_key(api_key: str) -> None:
    """Check whether Anthropic accepts the key for a model-list request."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=15.0)
    try:
        client.models.list(limit=1)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        raise KeyRejectedError("The key was not accepted by Anthropic") from None
    except Exception:  # network, rate limit, provider outage; never echo details (may hold key)
        raise ProviderUnavailableError("Could not reach Anthropic to verify the key") from None


def verify_provider_key(api_key: str, provider: str) -> None:
    if provider == PROVIDER:
        verify_anthropic_key(api_key)
        return
    try:
        CompatibleLLMProvider(provider, "", api_key).verify()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):
            raise KeyRejectedError("The provider did not accept the key") from None
        raise ProviderUnavailableError("The key could not be verified") from None
    except (httpx.RequestError, UnicodeError):
        raise ProviderUnavailableError("The key could not be verified") from None


def list_provider_models(api_key: str, provider: str) -> dict[str, str]:
    import anthropic

    try:
        if provider == PROVIDER:
            client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=15.0)
            return {
                model.id: model.display_name
                for model in client.models.list(limit=100)
                if model.id.startswith("claude-") and re.fullmatch(MODEL_ID_PATTERN, model.id)
            }
        return CompatibleLLMProvider(provider, "", api_key).models()
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        raise KeyRejectedError("The provider did not accept the key") from None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):
            raise KeyRejectedError("The provider did not accept the key") from None
        raise ProviderUnavailableError("The model list could not be loaded") from None
    except (
        anthropic.APIError, httpx.RequestError, AttributeError, KeyError, TypeError, ValueError
    ):
        raise ProviderUnavailableError("The model list could not be loaded") from None


def provider_for(row: dict[str, Any] | None) -> LLMProvider:
    """The practitioner's own LLM provider, or NoUserKeyError / VaultError."""
    if row is None:
        raise NoUserKeyError("No AI key saved")
    if not is_active(row):
        raise KeyPausedError("AI key is paused")
    provider = row.get("provider", PROVIDER)
    key = decrypt_secret(row["encrypted_api_key"])
    if provider == PROVIDER:
        model = row["model"] if row["model"].startswith("claude-") else DEFAULT_MODEL
        return AnthropicLLMProvider(model=model, api_key=key)
    return CompatibleLLMProvider(provider, row["model"], key)


__all__ = [
    "ACTIVE_OPTIONS",
    "ALLOWED_MODELS",
    "DEFAULT_ACTIVE_FOR",
    "DEFAULT_MODEL",
    "PROVIDER",
    "ActiveFor",
    "KeyPausedError",
    "KeyRejectedError",
    "NoUserKeyError",
    "active_until_from_now",
    "is_active",
    "ProviderUnavailableError",
    "SupabaseUserAIStore",
    "UserAIStore",
    "VaultError",
    "provider_for",
    "verify_anthropic_key",
]
