"""Pydantic response schemas for the FastAPI layer."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response shape for GET /health."""

    app: str
    status: str
    version: str
    environment: str
    services: dict[str, bool]
