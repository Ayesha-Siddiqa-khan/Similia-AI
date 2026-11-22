"""Smoke tests for the GraphQL endpoint."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_graphql_health_query() -> None:
    response = client.post("/graphql", json={"query": "{ health }"})
    assert response.status_code == 200
    assert response.json() == {"data": {"health": "Similia AI GraphQL API is operational"}}
