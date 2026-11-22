"""Application factory and ASGI entrypoint.

Run locally: uv run uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter

from app.api.routes.ai_settings import router as ai_settings_router
from app.api.routes.cases import router as cases_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.monitor import router as monitor_router
from app.core.config import get_settings
from app.core.request_log import RequestLogMiddleware, configure_logging
from app.core.startup import check_configuration
from app.graphql.schema import schema
from app.services.case_db import CaseStoreError


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    """Production refuses to start with an unsafe configuration; development only warns."""
    check_configuration(get_settings())
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application with CORS and GraphQL mounted."""
    settings = get_settings()
    # The interactive API docs describe every endpoint; they are for development only.
    production = settings.environment.strip().lower() == "production"
    configure_logging()
    application = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.add_middleware(RequestLogMiddleware)

    @application.exception_handler(CaseStoreError)
    async def case_store_error(_request: Request, _exc: CaseStoreError) -> JSONResponse:
        # Details stay server-side: they may contain patient data.
        return JSONResponse({"detail": "Patient records are temporarily unavailable"}, 503)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 body echoes the rejected INPUT back. For case text that is patient
        # information, so only the field name and the rule that failed are returned.
        problems: list[str] = []
        for error in exc.errors()[:5]:
            where = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            message = str(error.get("msg", "invalid value"))
            problems.append(f"{where}: {message}" if where else message)
        return JSONResponse({"detail": "; ".join(problems)[:300] or "Invalid request"}, 422)

    application.include_router(health_router)
    application.include_router(ai_settings_router)
    application.include_router(cases_router)
    application.include_router(knowledge_router)
    application.include_router(monitor_router)
    application.include_router(GraphQLRouter(schema), prefix="/graphql")
    return application


app = create_app()
