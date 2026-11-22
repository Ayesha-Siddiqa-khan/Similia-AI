"""LLM provider abstraction.

The application depends only on the LLMProvider protocol; the concrete adapter
(Claude via langchain-anthropic today) is selected by configuration, so the
provider can be swapped later without touching call sites.
"""

from typing import Protocol

from app.core.config import get_settings


class LLMProvider(Protocol):
    """Anything that can supply a chat model to the app."""

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

    def chat_model(self) -> object:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=self._model, api_key=self._api_key or "placeholder")


def get_llm_provider() -> LLMProvider:
    """Factory for the configured LLM provider."""
    settings = get_settings()
    return AnthropicLLMProvider(model=settings.anthropic_model, api_key=settings.anthropic_api_key)
