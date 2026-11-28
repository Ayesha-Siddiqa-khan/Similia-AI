"""Clinical research when the search actually returns passages (mocked: no provider calls)."""

from types import SimpleNamespace

import pytest

from app.ai.rag import clinical_research as pipeline
from app.ai.rag.case_analysis import NormalisedCase, SearchQuery
from app.ai.rag.retrieval import RetrievedPassage


def _hit(chunk_id: str, book_id: str, category: str, content: str) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id,
        book_id=book_id,
        section_id=None,
        book_title=f"Book {book_id}",
        book_category=category,
        book_author=f"Author {book_id}",
        section_heading="Skin",
        section_path=["Skin"],
        content=content,
        similarity=0.6,
        metadata={"page_start": 12},
        retrieval_mode="keyword",
        matched_by=["keyword"],
    )


@pytest.fixture()
def stubbed(monkeypatch: pytest.MonkeyPatch):
    class Reasoner:
        def __init__(self, _llm):
            pass

        def normalise(self, _text, _language):
            return NormalisedCase(queries=[SearchQuery(text="knee stiffness worse in cold")])

    hits = {
        "repertory": [_hit("r1", "b1", "repertory", "Knee stiffness, worse in cold weather.")],
        "materia_medica": [
            _hit("m1", "b2", "materia_medica", "Stiffness of the knee which is worse from cold.")
        ],
    }
    monkeypatch.setattr(pipeline, "ClaudeReasoner", Reasoner)
    monkeypatch.setattr(pipeline, "book_completeness", lambda _db: {"b1": True, "b2": True})
    monkeypatch.setattr(pipeline, "prepare_queries", lambda *_a, **_k: None)
    monkeypatch.setattr(
        pipeline,
        "build_retriever",
        lambda *_a, **_kw: SimpleNamespace(
            mode="keyword",
            fallback_reason=None,
            search=lambda _q, category, **_k: (hits[category], 0),
        ),
    )


def run(flags: list[str] | None = None, disposition: str | None = None) -> dict:
    # llm is a bare object: the interpretation step is skipped when it is None, and the
    # normaliser is stubbed, so nothing here can reach a model.
    return pipeline.research(
        object(),
        object(),
        "Recorded symptoms: knee stiffness, worse in cold.",
        "en",
        "keyword",
        flags or [],
        [],
        disposition,
    )


def test_research_with_search_hits_returns_the_sources(stubbed, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "structured_model",
        lambda *_a: SimpleNamespace(
            invoke=lambda _m: pipeline.ResearchInterpretation(
                associations=[], missing_information=["Is the knee swollen?"]
            )
        ),
    )
    llm = SimpleNamespace(chat_model=lambda: object())
    result = pipeline.research(
        object(), llm, "knee stiffness worse in cold", "en", "keyword", [], [], None
    )
    assert result["coverage"] == "retrieved"
    assert {s["chunk_id"] for s in result["sources"]} == {"r1", "m1"}
    assert result["searches"] and all(s["hits"] >= 1 for s in result["searches"])
    assert result["missing_information"] == ["Is the knee swollen?"]


def test_an_urgent_case_with_a_disposition_still_lists_sources_without_associations(
    stubbed, monkeypatch
) -> None:
    def never(*_a):
        raise AssertionError("an urgent case is never interpreted into remedy associations")

    monkeypatch.setattr(pipeline, "structured_model", never)
    llm = SimpleNamespace(chat_model=lambda: object())
    result = pipeline.research(
        object(), llm, "knee stiffness", "en", "keyword", ["Urgent finding"], [], "Assessed today"
    )
    assert result["coverage"] != "search_failed"
    assert len(result["sources"]) == 2 and result["associations"] == []
