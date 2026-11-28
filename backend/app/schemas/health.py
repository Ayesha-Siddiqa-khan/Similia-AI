"""Pydantic response schemas for the FastAPI layer."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response shape for GET /health."""

    app: str
    status: str
    version: str
    instance_id: str | None = None
    environment: str
    services: dict[str, bool]
