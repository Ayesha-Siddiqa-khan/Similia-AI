"""Each practitioner manages their own AI API key. The key is write-only: never returned."""

from datetime import datetime, timezone
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from app.api.auth import require_practitioner
from app.core.config import get_settings
from app.core.vault import VaultError, encrypt_secret, vault_ready
from app.services import ai_limits
from app.services.case_db import CaseStore, SupabaseCaseStore
from app.services.supabase import get_supabase_admin_client
from app.services.user_ai import (
    ACTIVE_OPTIONS,
    ALLOWED_MODELS,
    DEFAULT_ACTIVE_FOR,
    DEFAULT_MODEL,
    PROVIDER,
    KeyRejectedError,
    ProviderUnavailableError,
    SupabaseUserAIStore,
    UserAIStore,
    active_until_from_now,
    is_active,
    parse_active_until,
    verify_anthropic_key,
)

router = APIRouter(prefix="/api", tags=["ai-settings"])
Owner = Annotated[str, Depends(require_practitioner)]


def _require_db() -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured")


def get_ai_store() -> UserAIStore:
    _require_db()
    return SupabaseUserAIStore(get_supabase_admin_client())


def get_audit_store() -> CaseStore:
    _require_db()
    return SupabaseCaseStore(get_supabase_admin_client())


def get_key_verifier() -> Callable[[str], None]:
    return verify_anthropic_key


AIStore = Annotated[UserAIStore, Depends(get_ai_store)]
Audit = Annotated[CaseStore, Depends(get_audit_store)]
Verifier = Annotated[Callable[[str], None], Depends(get_key_verifier)]


class ModelOption(BaseModel):
    id: str
    label: str


class UsageOut(BaseModel):
    used: int
    limit: int


class AIUsageOut(BaseModel):
    window_minutes: int = 60
    questions: UsageOut
    analyses: UsageOut


class AISettingsOut(BaseModel):
    configured: bool
    vault_ready: bool
    provider: str = PROVIDER
    key_last4: str | None = None
    model: str = DEFAULT_MODEL
    validated_at: datetime | None = None
    models: list[ModelOption] = [ModelOption(id=k, label=v) for k, v in ALLOWED_MODELS.items()]
    active: bool = False
    active_until: datetime | None = None
    active_options: list[ModelOption] = [
        ModelOption(id=k, label=v[0]) for k, v in ACTIVE_OPTIONS.items()
    ]
    usage: AIUsageOut | None = None


class AISettingsIn(BaseModel):
    # SecretStr keeps the key out of reprs, logs and error messages.
    api_key: SecretStr | None = Field(default=None, min_length=20, max_length=400)
    model: str = DEFAULT_MODEL
    active_for: Literal["1d", "7d", "30d"] = DEFAULT_ACTIVE_FOR  # used when a key is saved


class ActivateIn(BaseModel):
    active_for: Literal["1d", "7d", "30d"] = DEFAULT_ACTIVE_FOR


def _out(row: dict | None) -> AISettingsOut:
    if row is None:
        return AISettingsOut(configured=False, vault_ready=vault_ready())
    return AISettingsOut(
        configured=True,
        vault_ready=vault_ready(),
        key_last4=row["key_last4"],
        model=row["model"],
        validated_at=row.get("validated_at"),
        active=is_active(row),
        active_until=parse_active_until(row),
    )


def _with_usage(out: AISettingsOut, audit: CaseStore, owner: str) -> AISettingsOut:
    out.usage = AIUsageOut(**ai_limits.usage(audit, owner))
    return out


@router.get("/settings/ai", response_model=AISettingsOut)
def get_ai_settings(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.put("/settings/ai", response_model=AISettingsOut)
def put_ai_settings(
    body: AISettingsIn, owner: Owner, store: AIStore, audit: Audit, verify: Verifier
) -> AISettingsOut:
    if body.model not in ALLOWED_MODELS:
        raise HTTPException(422, "Choose one of the listed models")
    existing = store.get(owner)
    if body.api_key is None:  # change the model only, keep the stored key
        if existing is None:
            raise HTTPException(422, "Enter your API key")
        store.save(owner, {**existing, "model": body.model})
        audit.audit(owner, "ai_settings.model", "ai_settings", None)
        return _with_usage(_out(store.get(owner)), audit, owner)

    key = body.api_key.get_secret_value().strip()
    if any(c.isspace() for c in key):
        raise HTTPException(422, "The key must not contain spaces or line breaks")
    if not vault_ready():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Key storage is not set up on the server (APP_ENCRYPTION_KEY missing)",
        )
    try:
        verify(key)
    except KeyRejectedError:
        raise HTTPException(
            422, "The key was not accepted by Anthropic. Check it and try again"
        ) from None
    except ProviderUnavailableError:
        raise HTTPException(502, "Could not reach Anthropic to verify the key. Try again") from None
    try:
        encrypted = encrypt_secret(key)
    except VaultError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Key storage is not set up correctly"
        ) from None
    store.save(
        owner,
        {
            "provider": PROVIDER,
            "encrypted_api_key": encrypted,
            "key_last4": key[-4:],
            "model": body.model,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "active_until": active_until_from_now(body.active_for).isoformat(),
        },
    )
    audit.audit(owner, "ai_settings.key_saved", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.post("/settings/ai/activate", response_model=AISettingsOut)
def activate_ai_key(body: ActivateIn, owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    """Turn a saved key back on for 1 day, 1 week or 1 month, without re-entering it."""
    row = store.get(owner)
    if row is None:
        raise HTTPException(404, "No AI key saved yet")
    store.save(owner, {**row, "active_until": active_until_from_now(body.active_for).isoformat()})
    audit.audit(owner, "ai_settings.activated", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.post("/settings/ai/deactivate", response_model=AISettingsOut)
def deactivate_ai_key(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    """Pause the key right now. It stays saved (encrypted) and can be turned on again."""
    row = store.get(owner)
    if row is None:
        raise HTTPException(404, "No AI key saved yet")
    store.save(owner, {**row, "active_until": datetime.now(timezone.utc).isoformat()})
    audit.audit(owner, "ai_settings.paused", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.delete("/settings/ai", response_model=AISettingsOut)
def delete_ai_settings(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    store.delete(owner)
    audit.audit(owner, "ai_settings.key_removed", "ai_settings", None)
    return _with_usage(_out(None), audit, owner)
