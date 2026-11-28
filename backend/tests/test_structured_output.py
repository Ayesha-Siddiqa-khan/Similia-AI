"""Structured-output wiring: the method must match what the model supports.

Sonnet 5.5 and Opus 5.5 advertise native structured output and reject forced
tool calling, so they must use `method="json_schema"`. Models without that
capability (Haiku 5.5) keep the function-calling path. Every call site must
pass its original schema unchanged.
"""

from typing import Any

from app.ai.rag.case_analysis import ClaudeReasoner, NormalisedCase, RankedOutput
from app.ai.rag.case_questions import ClaudeQuestionWriter, FollowUps
from app.ai.rag.report_translation import ClaudeReportTranslator, UrduReport
from app.api.routes.cases import _provider_error_reason, _provider_error_type
from app.services.llm import structured_output_method


class FakeStructured:
    def __init__(self, schema: type) -> None:
        self._schema = schema

    def invoke(self, messages: list[Any]) -> Any:
        return self._schema()


class FakeChatModel:
    """Records how the caller asked for structured output."""

    def __init__(self, structured_output: bool | None) -> None:
        self.profile = (
            None if structured_output is None else {"structured_output": structured_output}
        )
        self.calls: list[tuple[type, str | None]] = []

    def with_structured_output(
        self, schema: type, *, method: str | None = None, **kwargs: Any
    ) -> FakeStructured:
        self.calls.append((schema, method))
        return FakeStructured(schema)


class FakeProvider:
    def __init__(self, model: FakeChatModel) -> None:
        self._model = model

    def chat_model(self) -> FakeChatModel:
        return self._model


def exercise_all_call_sites(model: FakeChatModel) -> None:
    provider = FakeProvider(model)
    reasoner = ClaudeReasoner(provider)
    reasoner.normalise("headache, worse in the sun", "en")
    reasoner.rank("headache, worse in the sun", {"P1": "Belladonna, headache from sun"})
    ClaudeQuestionWriter(provider).write("headache, worse in the sun", include_urdu=False)
    ClaudeReportTranslator(provider).to_urdu(
        {"chief_complaint": "headache", "remedies": [], "cautions": []}
    )


EXPECTED_SCHEMAS = [NormalisedCase, RankedOutput, FollowUps, UrduReport]


def test_native_structured_output_models_use_json_schema() -> None:
    model = FakeChatModel(structured_output=True)
    exercise_all_call_sites(model)

    assert [schema for schema, _ in model.calls] == EXPECTED_SCHEMAS
    assert [method for _, method in model.calls] == ["json_schema"] * 4


def test_models_without_native_structured_output_keep_function_calling() -> None:
    model = FakeChatModel(structured_output=False)
    exercise_all_call_sites(model)

    assert [schema for schema, _ in model.calls] == EXPECTED_SCHEMAS
    assert [method for _, method in model.calls] == ["function_calling"] * 4


def test_unknown_profile_falls_back_to_function_calling() -> None:
    model = FakeChatModel(structured_output=None)
    exercise_all_call_sites(model)

    assert [method for _, method in model.calls] == ["function_calling"] * 4


def test_method_requires_an_explicit_true_capability() -> None:
    assert structured_output_method(FakeChatModel(structured_output=True)) == "json_schema"
    assert structured_output_method(FakeChatModel(structured_output=False)) == "function_calling"

    model = FakeChatModel(structured_output=None)
    model.profile = {"structured_output": "true"}
    assert structured_output_method(model) == "function_calling"


class ProviderError(Exception):
    def __init__(self, message: str, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.body = body


def test_provider_error_reason_is_a_fixed_code() -> None:
    assert _provider_error_reason(ProviderError("Your credit balance is too low")) == "billing"
    assert (
        _provider_error_reason(ProviderError("prompt is too long: 210000 tokens"))
        == "context_length"
    )
    assert (
        _provider_error_reason(ProviderError("tools.0: unsupported tool_choice value"))
        == "tool_choice"
    )
    assert (
        _provider_error_reason(
            ProviderError("output_config.format: schema uses an unsupported keyword")
        )
        == "structured_output"
    )
    assert _provider_error_reason(ProviderError("max_tokens is too large")) == "max_tokens"
    assert _provider_error_reason(ProviderError("temperature is not supported")) == "sampling"
    assert _provider_error_reason(ProviderError("model not found")) == "model"
    assert _provider_error_reason(ProviderError("something else entirely")) == "unclassified"
    assert _provider_error_reason(Exception("something else entirely")) == "unclassified"


def test_provider_error_type_reads_only_the_error_class() -> None:
    exc = ProviderError("ignored", body={"error": {"type": "invalid_request_error"}})
    assert _provider_error_type(exc) == "invalid_request_error"
    assert _provider_error_type(ProviderError("ignored")) == "unknown"
    assert (
        _provider_error_type(ProviderError("ignored", body={"error": "not a mapping"}))
        == "unknown"
    )
