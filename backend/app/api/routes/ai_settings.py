"""Each practitioner manages their own AI API key. The key is write-only: never returned."""

from datetime import datetime, timezone
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest import APIError
from pydantic import BaseModel, Field, SecretStr

from app.ai.rag.case_analysis import ClaudeReasoner
from app.ai.rag.guard import embedding_paused
from app.api.auth import require_practitioner
from app.core.config import get_settings
from app.core.vault import VaultError, decrypt_secret, encrypt_secret, vault_ready
from app.services import ai_limits, knowledge_db
from app.services.case_db import CaseStore, SupabaseCaseStore
from app.services.compatible_llm import (
    COMPATIBLE_PROVIDERS,
    MODEL_ID_PATTERN,
    CompatibleProviderError,
)
from app.services.embeddings import get_embedding_provider
from app.services.supabase import get_supabase_admin_client
from app.services.user_ai import (
    ACTIVE_OPTIONS,
    ALLOWED_MODELS,
    DEFAULT_ACTIVE_FOR,
    DEFAULT_MODEL,
    PROVIDER,
    PROVIDERS,
    KeyPausedError,
    KeyRejectedError,
    NoUserKeyError,
    ProviderUnavailableError,
    SupabaseUserAIStore,
    UserAIStore,
    active_until_from_now,
    is_active,
    list_provider_models,
    parse_active_until,
    provider_for,
    verify_provider_key,
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


def get_key_verifier() -> Callable[[str, str], None]:
    return verify_provider_key


AIStore = Annotated[UserAIStore, Depends(get_ai_store)]
Audit = Annotated[CaseStore, Depends(get_audit_store)]
Verifier = Annotated[Callable[[str, str], None], Depends(get_key_verifier)]


class ModelOption(BaseModel):
    id: str
    label: str


class ProviderOption(ModelOption):
    model_example: str | None = None


class UsageOut(BaseModel):
    used: int
    limit: int


class AIUsageOut(BaseModel):
    window_minutes: int = 60
    questions: UsageOut
    analyses: UsageOut
    daily_analyses: UsageOut


class ConnectionCheck(BaseModel):
    service: str
    model: str | None = None
    status: Literal["passed", "failed", "skipped"]
    detail: str
    upstream_status: int | None = None


class AISettingsOut(BaseModel):
    configured: bool
    vault_ready: bool
    provider: str = PROVIDER
    providers: list[ProviderOption] = [
        ProviderOption(id=PROVIDER, label=PROVIDERS[PROVIDER]),
        *[
            ProviderOption(id=key, label=info.label, model_example=info.model_example)
            for key, info in COMPATIBLE_PROVIDERS.items()
        ],
    ]
    key_last4: str | None = None
    model: str = DEFAULT_MODEL
    validated_at: datetime | None = None
    models: list[ModelOption] = [ModelOption(id=k, label=v) for k, v in ALLOWED_MODELS.items()]
    active: bool = False
    active_until: datetime | None = None
    hourly_analysis_limit: int | None = None
    daily_analysis_limit: int | None = None
    active_options: list[ModelOption] = [
        ModelOption(id=k, label=v[0]) for k, v in ACTIVE_OPTIONS.items()
    ]
    usage: AIUsageOut | None = None


class AISettingsIn(BaseModel):
    # SecretStr keeps the key out of reprs, logs and error messages.
    api_key: SecretStr | None = Field(default=None, min_length=20, max_length=400)
    provider: str | None = None
    model: str | None = Field(default=None, pattern=MODEL_ID_PATTERN)
    active_for: Literal["1d", "7d", "30d"] = DEFAULT_ACTIVE_FOR  # used when a key is saved


class ActivateIn(BaseModel):
    active_for: Literal["1d", "7d", "30d"] = DEFAULT_ACTIVE_FOR


class AnalysisLimitIn(BaseModel):
    hourly_analysis_limit: Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)] | None = None
    daily_analysis_limit: Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)] | None = None


class ModelCatalogIn(BaseModel):
    provider: str
    api_key: SecretStr | None = Field(default=None, min_length=20, max_length=400)


def _out(row: dict | None) -> AISettingsOut:
    if row is None:
        return AISettingsOut(configured=False, vault_ready=vault_ready())
    return AISettingsOut(
        configured=True,
        vault_ready=vault_ready(),
        provider=row.get("provider", PROVIDER),
        key_last4=row["key_last4"],
        model=row["model"],
        validated_at=row.get("validated_at"),
        active=is_active(row),
        active_until=parse_active_until(row),
        hourly_analysis_limit=row.get("hourly_analysis_limit"),
        daily_analysis_limit=row.get("daily_analysis_limit"),
    )


def _with_usage(out: AISettingsOut, audit: CaseStore, owner: str) -> AISettingsOut:
    out.usage = AIUsageOut(
        **ai_limits.usage(
            audit, owner, hourly_analysis_limit=out.hourly_analysis_limit,
            daily_analysis_limit=out.daily_analysis_limit,
        )
    )
    return out


def _update_key(
    store: UserAIStore, owner: str, provider: str, changes: dict[str, str | int | None]
) -> None:
    if not store.update(owner, provider, changes):
        raise HTTPException(409, "AI settings changed. Reload the page and try again.")


@router.get("/settings/ai", response_model=AISettingsOut)
def get_ai_settings(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    return _with_usage(_out(store.get(owner)), audit, owner)


def _check_failure(service: str, model: str, exc: Exception) -> ConnectionCheck:
    code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    code = code if type(code) is int else None
    reason = exc.message if isinstance(exc, CompatibleProviderError) else ""
    detail = {
        "billing": "The provider rejected the request because of billing or available credits.",
        "account_restriction": "The provider blocked generation for this account.",
        "invalid_output": "The provider responded with invalid structured output.",
        "unavailable": "The provider did not respond to the request.",
    }.get(reason) or {
        400: "The provider rejected the request for this model.",
        401: "The provider did not accept the API key.",
        402: "The provider rejected the request because of billing or available credits.",
        403: "The API key or account does not have access to this request.",
        404: "The requested model was not found for this account.",
        429: "The provider reached its rate or quota limit.",
    }.get(code, "The provider check failed.")
    return ConnectionCheck(
        service=service, model=model, status="failed", detail=detail,
        upstream_status=code,
    )


@router.post("/settings/ai/diagnostics", response_model=list[ConnectionCheck])
def check_ai_connections(owner: Owner, store: AIStore, audit: Audit) -> list[ConnectionCheck]:
    """Test generation and semantic search with fixed text and the saved credentials."""
    try:
        ai_limits.enforce(audit, owner, "questions")
    except ai_limits.RateLimitedError as exc:
        raise HTTPException(429, exc.message) from None
    audit.audit(owner, "ai_settings.connection_check", "ai_settings", None)
    row = store.get(owner)
    service = PROVIDERS.get(row.get("provider", PROVIDER), "AI provider") if row else "AI provider"
    model = row.get("model", DEFAULT_MODEL) if row else DEFAULT_MODEL
    try:
        llm = provider_for(row)
        model = llm.model
        ClaudeReasoner(llm).normalise("Synthetic connection check: a blue notebook.", "en")
        generation = ConnectionCheck(
            service=service, model=model, status="passed", detail="Structured generation worked."
        )
    except (NoUserKeyError, KeyPausedError):
        generation = ConnectionCheck(
            service=service, status="skipped", detail="Save or enable an AI key first."
        )
    except VaultError:
        generation = ConnectionCheck(
            service=service, model=model, status="failed", detail="Key storage could not be read."
        )
    except Exception as exc:
        generation = _check_failure(service, model, exc)

    settings = get_settings()
    voyage_model = settings.voyage_model
    if embedding_paused():
        return [generation, ConnectionCheck(
            service="Voyage", model=voyage_model, status="skipped", detail="Embeddings are paused."
        )]
    if not settings.voyage_api_key:
        return [generation, ConnectionCheck(
            service="Voyage", model=voyage_model, status="skipped",
            detail="The server has no Voyage key configured."
        )]
    try:
        vector = get_embedding_provider(max_attempts=1).embed_query("blue notebook")
    except Exception as exc:
        return [generation, _check_failure("Voyage", voyage_model, exc)]

    voyage = ConnectionCheck(
        service="Voyage", model=voyage_model, status="passed", detail="Query embedding worked."
    )
    try:
        knowledge_db.search_chunks(get_supabase_admin_client(), vector, match_count=1)
        library = ConnectionCheck(
            service="Semantic source library", status="passed", detail="Vector search responded."
        )
    except Exception:
        library = ConnectionCheck(
            service="Semantic source library", status="failed", detail="Vector search failed."
        )
    return [generation, voyage, library]


@router.put("/settings/ai/analysis-limit", response_model=AISettingsOut)
def put_analysis_limit(
    body: AnalysisLimitIn, owner: Owner, store: AIStore, audit: Audit
) -> AISettingsOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Enter an hourly or daily analysis limit")
    row = store.get(owner)
    if row is None:
        raise HTTPException(404, "Save an AI provider key first")
    try:
        _update_key(store, owner, row.get("provider", PROVIDER), changes)
    except APIError as error:
        if "daily_analysis_limit" in changes and error.code in {"PGRST204", "42703"}:
            raise HTTPException(
                409, "Apply the daily analysis limit migration in Supabase.",
            ) from None
        raise
    for field in changes:
        audit.audit(owner, f"ai_settings.{field}", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.post("/settings/ai/models", response_model=list[ModelOption])
def get_ai_models(body: ModelCatalogIn, owner: Owner, store: AIStore) -> list[ModelOption]:
    label = PROVIDERS.get(body.provider)
    if label is None:
        raise HTTPException(422, "Choose one of the listed AI providers")
    if body.api_key is not None:
        key = body.api_key.get_secret_value().strip()
        if not key or any(c.isspace() for c in key):
            raise HTTPException(422, "The key must not contain spaces or line breaks")
    else:
        row = store.get(owner)
        if row is None or row.get("provider", PROVIDER) != body.provider:
            raise HTTPException(422, "Enter an API key for the selected provider")
        try:
            key = decrypt_secret(row["encrypted_api_key"])
        except VaultError:
            raise HTTPException(503, "Key storage is not set up correctly") from None
    try:
        models = list_provider_models(key, body.provider)
    except KeyRejectedError:
        raise HTTPException(422, f"{label} did not accept the key for listing models") from None
    except ProviderUnavailableError:
        raise HTTPException(502, f"Could not load models from {label}. Try again.") from None
    return [
        ModelOption(id=model_id, label=name)
        for model_id, name in sorted(models.items(), key=lambda item: item[1].casefold())
    ]


@router.put("/settings/ai", response_model=AISettingsOut)
def put_ai_settings(
    body: AISettingsIn, owner: Owner, store: AIStore, audit: Audit, verify: Verifier
) -> AISettingsOut:
    existing = store.get(owner)
    existing_provider = existing.get("provider", PROVIDER) if existing else PROVIDER
    provider = body.provider if body.provider is not None else PROVIDER
    if provider not in PROVIDERS:
        raise HTTPException(422, "Choose one of the listed AI providers")
    label = PROVIDERS[provider]
    model = body.model or (DEFAULT_MODEL if provider == PROVIDER else None)
    if provider == PROVIDER and model is not None and not model.startswith("claude-"):
        raise HTTPException(422, "Choose one of the listed models")
    if model is None:
        raise HTTPException(422, "Enter the provider's chat model ID")
    if body.api_key is None:  # change the model only, keep the stored key
        if existing is None:
            raise HTTPException(422, "Enter your API key")
        if provider != existing_provider:
            raise HTTPException(422, "Enter an API key for the selected provider")
        _update_key(store, owner, existing_provider, {"model": model})
        audit.audit(owner, "ai_settings.model", "ai_settings", None)
        return _with_usage(_out(store.get(owner)), audit, owner)

    key = body.api_key.get_secret_value().strip()
    if not key or any(c.isspace() for c in key):
        raise HTTPException(422, "The key must not contain spaces or line breaks")
    if not vault_ready():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Key storage is not set up on the server (APP_ENCRYPTION_KEY missing)",
        )
    try:
        verify(key, provider)
    except KeyRejectedError:
        raise HTTPException(
            422, f"The key was not accepted by {label}. Check it and try again"
        ) from None
    except ProviderUnavailableError:
        raise HTTPException(502, f"Could not reach {label} to verify the key. Try again") from None
    try:
        encrypted = encrypt_secret(key)
    except VaultError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Key storage is not set up correctly"
        ) from None
    store.save(
        owner,
        {
            "provider": provider,
            "encrypted_api_key": encrypted,
            "key_last4": key[-4:],
            "model": model,
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
    _update_key(store, owner, row.get("provider", PROVIDER), {
        "active_until": active_until_from_now(body.active_for).isoformat(),
    })
    audit.audit(owner, "ai_settings.activated", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.post("/settings/ai/deactivate", response_model=AISettingsOut)
def deactivate_ai_key(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    """Pause the key right now. It stays saved (encrypted) and can be turned on again."""
    row = store.get(owner)
    if row is None:
        raise HTTPException(404, "No AI key saved yet")
    _update_key(store, owner, row.get("provider", PROVIDER), {
        "active_until": datetime.now(timezone.utc).isoformat(),
    })
    audit.audit(owner, "ai_settings.paused", "ai_settings", None)
    return _with_usage(_out(store.get(owner)), audit, owner)


@router.delete("/settings/ai", response_model=AISettingsOut)
def delete_ai_settings(owner: Owner, store: AIStore, audit: Audit) -> AISettingsOut:
    store.delete(owner)
    audit.audit(owner, "ai_settings.key_removed", "ai_settings", None)
    return _with_usage(_out(None), audit, owner)
