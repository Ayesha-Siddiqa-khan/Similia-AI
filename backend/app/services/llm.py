"""LLM provider abstraction.

The application depends only on the LLMProvider protocol; the concrete adapter
(Claude via langchain-anthropic today) is selected by configuration, so the
provider can be swapped later without touching call sites.
"""

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from app.core.config import get_settings

StructuredOutputMethod = Literal["function_calling", "json_schema"]


def structured_output_method(chat_model: object) -> StructuredOutputMethod:
    """The structured-output method the model's profile actually supports.

    Anthropic models that advertise native structured output (Sonnet 5.5,
    Opus 5.5) also reject forced tool calling, so they must use the JSON-schema
    response format. Everything else keeps the default function-calling path.
    """
    profile = getattr(chat_model, "profile", None)
    if isinstance(profile, Mapping) and profile.get("structured_output") is True:
        return "json_schema"
    return "function_calling"


def structured_model(chat_model: Any, schema: type[Any]) -> Any:
    """Bind `schema` to `chat_model` with the method that model supports."""
    return chat_model.with_structured_output(
        schema, method=structured_output_method(chat_model)
    )


class LLMProvider(Protocol):
    """Anything that can supply a chat model to the app."""

    @property
    def model(self) -> str: ...

    def chat_model(self) -> object:
        """Return a LangChain chat model instance."""
        ...


class AnthropicLLMProvider:
    """Claude via the langchain-anthropic integration.

    ChatAnthropic is constructed lazily so importing this module (and starting
    the app) never triggers network calls or requires an API key.
    """

    def __init__(self, model: str, api_key: str) -> None:
        self._model = model
        self._api_key = api_key

    @property
    def model(self) -> str:
        return self._model

    def chat_model(self) -> object:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=self._model, api_key=self._api_key or "placeholder")


def get_llm_provider() -> LLMProvider:
    """Factory for the configured LLM provider."""
    settings = get_settings()
    return AnthropicLLMProvider(model=settings.anthropic_model, api_key=settings.anthropic_api_key)
