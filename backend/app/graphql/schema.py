"""Strawberry GraphQL schema.

GraphQL covers selected application data operations; REST stays available for
health checks, uploads, and future AI/RAG endpoints. No feature is implemented
in both unless there is a clear reason.
"""

import strawberry


@strawberry.type
class Query:
    """Root GraphQL query."""

    @strawberry.field
    def health(self) -> str:
        """Service liveness for the GraphQL API."""
        return "Similia AI GraphQL API is operational"


schema = strawberry.Schema(Query)
