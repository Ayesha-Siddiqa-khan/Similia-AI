"""Centralised environment configuration (pydantic-settings).

All environment variables are read here; nothing else in the app reads os.environ.
Secrets come from .env locally and from the deployment environment in production.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Env names match the field names (UPPER_CASE)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Similia AI API"
    environment: str = "development"
    # Comma-separated list, e.g. "http://localhost:3000,http://localhost:3001"
    cors_origins: str = "http://localhost:3000"

    # Supabase (never expose secret/service-role keys to the frontend)
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""

    # LLM (provider-agnostic: only the adapter knows it is Anthropic today)
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # Server-side secret (Fernet key) that encrypts users' own AI API keys at rest.
    # Generate once with cryptography.fernet.Fernet.generate_key() (see docs/ai-keys.md).
    app_encryption_key: str = ""
    # Older keys, comma separated, still accepted for decryption while rotating the key above.
    app_encryption_key_previous: str = ""

    # Hourly AI request limits per practitioner (they pay for their own key; this stops runaways).
    ai_questions_per_hour: int = 30
    ai_analyses_per_hour: int = 10
    # Daily and monthly ceilings per practitioner (0 = off). Counted from the audit log.
    ai_questions_per_day: int = 150
    ai_analyses_per_day: int = 40
    ai_analyses_per_month: int = 600

    # Embedding spend controls for book ingestion started from the website (enforced on the server).
    # Conservative defaults suit a provider free tier (about 3 requests and 10,000 tokens
    # per minute);
    # raise them only after checking your provider account's real limits.
    embedding_budget_tokens: int = 500_000  # total across all website ingestion jobs
    embedding_batch_tokens: int = 3_000  # largest single request
    embedding_requests_per_minute: int = 3  # 0 = do not pace requests
    # Search results below this similarity are not used as evidence in case analysis.
    rag_min_similarity: float = 0.25

    # Embeddings
    voyage_api_key: str = ""
    voyage_model: str = "voyage-4-lite"
    max_run_embedding_tokens: int = 200_000

    # LangSmith (tracing disabled by default)
    langsmith_api_key: str = ""
    langsmith_project: str = "similia-ai"
    langsmith_tracing: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins parsed from the comma-separated env value."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def provider_status(self) -> dict[str, bool]:
        """Whether each external provider is configured (booleans only, no secrets)."""
        return {
            "supabase": bool(self.supabase_url and self.supabase_publishable_key),
            "anthropic": bool(self.anthropic_api_key and self.anthropic_model),
            "voyage": bool(self.voyage_api_key),
        }


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
