"""Chat Completions adapters for the supported non-Anthropic providers."""

from __future__ import annotations

import json
import re
from base64 import b64encode
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

MODEL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,159}$"


@dataclass(frozen=True)
class CompatibleProvider:
    label: str
    base_url: str
    model_example: str
    verify_path: str = "/models"


COMPATIBLE_PROVIDERS = {
    "openai": CompatibleProvider("OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
    "gemini": CompatibleProvider(
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini-3.8-flash",
    ),
    "openrouter": CompatibleProvider(
        "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1-mini", "/key"
    ),
}


class CompatibleProviderError(RuntimeError):
    def __init__(self, status_code: int, reason: str = "") -> None:
        super().__init__("AI provider rejected the request")
        self.status_code = status_code
        self.message = reason


class CompatibleLLMProvider:
    def __init__(self, provider: str, model: str, api_key: str) -> None:
        self._provider = provider
        self.model = model
        self._api_key = api_key
        self._config = COMPATIBLE_PROVIDERS[provider]

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = (
            {"x-goog-api-key": self._api_key}
            if self._provider == "gemini"
            else {"Authorization": f"Bearer {self._api_key}"}
        )
        return httpx.request(
            method,
            self._config.base_url + path,
            headers=headers,
            follow_redirects=False,
            **kwargs,
        )

    def verify(self) -> None:
        self._request("GET", self._config.verify_path, timeout=15).raise_for_status()

    def models(self) -> dict[str, str]:
        if self._provider == "gemini":
            return self._gemini_models()
        path = "/models/user" if self._provider == "openrouter" else "/models"
        response = self._request("GET", path, timeout=15)
        if self._provider == "openrouter" and response.status_code == 403:
            # Ordinary OpenRouter keys may only have access to the public catalogue.
            self.verify()
            response = self._request("GET", "/models", timeout=15)
        response.raise_for_status()
        result = {}
        for entry in response.json()["data"]:
            model = entry.get("id", "")
            if re.fullmatch(MODEL_ID_PATTERN, model) and self._supports_chat(entry, model):
                result[model] = entry.get("name") or model
        return result

    def _gemini_models(self) -> dict[str, str]:
        result = {}
        params: dict[str, str | int] = {"pageSize": 1000}
        # Bound the number of upstream requests even for a malformed pagination token.
        for _ in range(3):
            response = self._request("GET", "/models", params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
            for entry in data.get("models", []):
                model = entry["name"].removeprefix("models/")
                if (
                    "generateContent" in entry.get("supportedGenerationMethods", [])
                    and re.fullmatch(MODEL_ID_PATTERN, model)
                    and self._supports_chat(entry, model)
                ):
                    result[model] = entry.get("displayName") or model
            if not (token := data.get("nextPageToken")):
                break
            params["pageToken"] = token
        return result

    def _supports_chat(self, entry: dict[str, Any], model: str) -> bool:
        if self._provider == "openrouter":
            architecture = entry.get("architecture") or {}
            return (
                "text" in (architecture.get("input_modalities") or [])
                and "text" in (architecture.get("output_modalities") or [])
                and "response_format" in (entry.get("supported_parameters") or [])
            )
        # These catalogues list multiple endpoint families without a chat capability flag.
        prefixes = ("gemini-",) if self._provider == "gemini" else ("gpt-", "o1", "o3", "o4")
        excluded = (
            "audio", "realtime", "transcribe", "tts", "image", "embedding", "search",
            "robotics", "computer-use", "deep-research", "-live",
        )
        return model.startswith(prefixes) and not any(part in model for part in excluded)

    def chat_model(self) -> Self:
        return self

    def with_structured_output[T: BaseModel](
        self, schema: type[T], *, method: str
    ) -> _StructuredCompletion[T]:
        return _StructuredCompletion(self, schema)

    def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            if self._provider == "gemini":
                return self._complete_gemini(messages)
            return self._complete_chat(messages)
        except httpx.RequestError:
            raise CompatibleProviderError(503, "unavailable") from None

    def _complete_chat(self, messages: list[dict[str, str]]) -> str:
        token_field = "max_completion_tokens" if self._provider == "openai" else "max_tokens"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            token_field: 8192,
        }
        if self._provider == "openrouter":
            payload["provider"] = {"data_collection": "deny", "require_parameters": True}
        response = self._request("POST", "/chat/completions", json=payload, timeout=45)
        self._check_completion(response)
        try:
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") != "stop" or not isinstance(content, str):
                raise ValueError
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            raise CompatibleProviderError(502, "invalid_output") from None
        return content

    def describe_images(self, instructions: str, labels: str, images: list[bytes]) -> str:
        if self._provider != "gemini":
            raise CompatibleProviderError(422, "image provider unsupported")
        parts = [
            {"inlineData": {"mimeType": "image/jpeg", "data": b64encode(image).decode("ascii")}}
            for image in images
        ]
        try:
            return self._complete_gemini(
                [{"content": instructions}, {"content": labels}], image_parts=parts,
            )
        except httpx.RequestError:
            raise CompatibleProviderError(503, "unavailable") from None

    def _complete_gemini(
        self, messages: list[dict[str, str]], *, image_parts: list[dict[str, Any]] | None = None,
    ) -> str:
        response = self._request(
            "POST",
            f"/models/{quote(self.model, safe='')}:generateContent",
            json={
                "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": message["content"]}, *(image_parts or [])],
                    }
                    for message in messages[1:]
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 8192,
                },
            },
            timeout=45,
        )
        self._check_completion(response)
        try:
            candidate = response.json()["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError
            return "".join(
                part["text"] for part in candidate["content"]["parts"]
                if "text" in part and not part.get("thought")
            )
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            raise CompatibleProviderError(502, "invalid_output") from None

    @staticmethod
    def _check_completion(response: httpx.Response) -> None:
        if not response.is_success:
            reason = "billing" if response.status_code == 402 else ""
            try:
                error = response.json()["error"]
                if error.get("code") in ("insufficient_quota", "billing_hard_limit_reached", 402):
                    reason = "billing"
                if error.get("status") == "FAILED_PRECONDITION":
                    reason = "account_restriction"
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
            if response.status_code == 404:
                reason = "model not found"
            raise CompatibleProviderError(response.status_code, reason)


@dataclass(frozen=True)
class _StructuredCompletion[T: BaseModel]:
    provider: CompatibleLLMProvider
    schema: type[T]

    def invoke(self, messages: Sequence[tuple[str, str]]) -> T:
        system = [text for role, text in messages if role == "system"]
        system.append(
            "Return a JSON object matching this schema: "
            + json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
        )
        request_messages = [
            {"role": "system", "content": "\n\n".join(system)},
            *[
                {"role": "user" if role == "human" else role, "content": text}
                for role, text in messages
                if role != "system"
            ],
        ]
        try:
            return self.schema.model_validate_json(self.provider.complete(request_messages))
        except ValidationError:
            raise CompatibleProviderError(502, "invalid_output") from None
