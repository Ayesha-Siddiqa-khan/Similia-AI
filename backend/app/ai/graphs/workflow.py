"""LangGraph workflows for Similia AI.

Phase 1 ships a minimal, fully offline CaseAnalysisWorkflow skeleton that
proves the LangGraph plumbing works. No LLM calls and no autonomous agent
behaviour are wired yet.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class CaseAnalysisState(TypedDict):
    """State passed between workflow nodes."""

    question: str
    retrieved: list[str]
    answer: str


class CaseAnalysisWorkflow:
    """Stateful case-analysis workflow (skeleton).

    retrieve -> respond. Both nodes are placeholders: retrieval returns no
    chunks and the answer stays empty until Phase 2 wires the RAG services
    and the configured LLM provider.
    """

    def __init__(self) -> None:
        self._graph = self._build()

    def _build(self) -> object:
        builder = StateGraph(CaseAnalysisState)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("respond", self._respond)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "respond")
        builder.add_edge("respond", END)
        return builder.compile()

    @staticmethod
    def _retrieve(state: CaseAnalysisState) -> dict[str, list[str]]:
        return {"retrieved": []}

    @staticmethod
    def _respond(state: CaseAnalysisState) -> dict[str, str]:
        return {"answer": ""}

    def run(self, question: str) -> CaseAnalysisState:
        """Execute the workflow offline and return the final state."""
        return self._graph.invoke({"question": question, "retrieved": [], "answer": ""})
