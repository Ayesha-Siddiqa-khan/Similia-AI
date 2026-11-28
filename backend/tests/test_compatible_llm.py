import json

import httpx
import pytest

from app.ai.rag.case_analysis import ClaudeReasoner
from app.services.compatible_llm import CompatibleLLMProvider, CompatibleProviderError
from app.services.user_ai import KeyRejectedError, verify_provider_key


@pytest.mark.parametrize(
    ("provider", "base", "verification"),
    [
        ("openai", "https://api.openai.com/v1", "/models"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta", "/models"),
        ("openrouter", "https://openrouter.ai/api/v1", "/key"),
    ],
)
def test_provider_verifies_key_and_returns_validated_case_queries(
    monkeypatch, provider: str, base: str, verification: str
) -> None:
    key = "synthetic-test-key"
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if provider == "gemini":
            assert request.headers["x-goog-api-key"] == key
        else:
            assert request.headers["authorization"] == f"Bearer {key}"
        if request.method == "GET":
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        if provider == "gemini":
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert body["contents"][0] == {"role": "user", "parts": [{"text": "Synthetic case"}]}
            return httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"queries":[{"text":"synthetic query"}]}'}]},
            }]})
        assert body["model"] == "synthetic-chat"
        assert body["messages"][1] == {"role": "user", "content": "Synthetic case"}
        assert body["response_format"] == {"type": "json_object"}
        if provider == "openrouter":
            assert body["provider"] == {"data_collection": "deny", "require_parameters": True}
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop",
            "message": {"content": '{"queries":[{"text":"synthetic query"}]}'},
        }]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        verify_provider_key(key, provider)
        reasoner = ClaudeReasoner(CompatibleLLMProvider(provider, "synthetic-chat", key))
        assert reasoner.normalise("Synthetic case", "en").queries[0].text == "synthetic query"

    generation = (
        "/models/synthetic-chat:generateContent" if provider == "gemini" else "/chat/completions"
    )
    assert calls == [("GET", base + verification), ("POST", base + generation)]


def test_gemini_catalog_uses_provider_names_and_excludes_non_chat_models(monkeypatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models"
        if not request.url.params.get("pageToken"):
            return httpx.Response(200, json={"models": [{
                "name": "models/gemini-embedding", "supportedGenerationMethods": ["embedContent"],
            }], "nextPageToken": "second"})
        return httpx.Response(200, json={"models": [{
            "name": "models/gemini-official-id", "displayName": "Gemini Official Name",
            "supportedGenerationMethods": ["generateContent"],
        }]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        assert CompatibleLLMProvider("gemini", "", "test-key").models() == {
            "gemini-official-id": "Gemini Official Name",
        }


def test_provider_errors_never_echo_the_upstream_body(monkeypatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(401, json={"message": "private provider data"})
        return httpx.Response(429, json={
            "error": {"code": "insufficient_quota", "message": "private provider data"},
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        with pytest.raises(KeyRejectedError):
            verify_provider_key("test-key", "openai")
        with pytest.raises(CompatibleProviderError) as error:
            CompatibleLLMProvider("openai", "test-model", "test-key").complete([])
    assert error.value.message == "billing"
    assert "private provider data" not in str(error.value)
