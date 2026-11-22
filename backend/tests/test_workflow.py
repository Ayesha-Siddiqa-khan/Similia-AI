"""Offline test for the LangGraph workflow skeleton (no API calls)."""

from app.ai.graphs import CaseAnalysisWorkflow


def test_workflow_runs_offline() -> None:
    result = CaseAnalysisWorkflow().run("What is Bryonia alba?")
    assert result["question"] == "What is Bryonia alba?"
    assert result["retrieved"] == []
    assert result["answer"] == ""
