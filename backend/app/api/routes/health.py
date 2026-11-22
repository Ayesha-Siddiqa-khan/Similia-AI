"""FastAPI REST routes (health now; uploads and AI workflow endpoints later)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.startup import readiness
from app.schemas.health import HealthResponse
from app.services.supabase import get_supabase_admin_client

router = APIRouter(tags=["health"])

APP_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness/readiness endpoint. Makes no external calls."""
    settings = get_settings()
    return HealthResponse(
        app=settings.app_name,
        status="ok",
        version=APP_VERSION,
        environment=settings.environment,
        services=settings.provider_status(),
    )


def _database_check() -> None:
    get_supabase_admin_client().table("knowledge_books").select("id").limit(1).execute()


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness: 200 only when configuration is sound and the database answers.

    Use this for the load balancer, `/health` for liveness. Reasons are short words, never
    connection details or secrets.
    """
    ok, checks = readiness(get_settings(), _database_check)
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "checks": checks}, 200 if ok else 503
    )
