"""Three search modes: semantic, keyword, hybrid. Honest labels and safe fallback."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.rag.retrieval import (
    HybridRetriever,
    KeywordRetriever,
    SemanticSearchError,
    VectorRetriever,
    build_retriever,
    describe_failure,
)
from app.api.auth import require_operator
from app.api.routes import knowledge
from app.main import create_app
from app.services import knowledge_db
from tests.test_case_analysis import passage


def hit(chunk_id: str, mode: str, score: float = 0.5):
    p = passage(chunk_id, score)
    p.retrieval_mode, p.matched_by = mode, [mode]
    return p


class Semantic:
    def __init__(self, ids: list[str]) -> None:
        self.ids, self.calls = ids, 0

    def search(self, *_a, **_k):
        self.calls += 1
        return [hit(i, "semantic", 0.9 - n / 10) for n, i in enumerate(self.ids)], 5


class Keyword:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids

    def search(self, *_a, **_k):
        return [hit(i, "keyword", 0.4 - n / 10) for n, i in enumerate(self.ids)], 2


class Refused(Exception):
    http_status = 403


class Broken:
    def search(self, *_a, **_k):
        raise Refused("secret body that must not be reported")


def test_hybrid_ranks_passages_found_by_both_searches_first_and_labels_each() -> None:
    retriever = HybridRetriever(Semantic(["a", "b", "c"]), Keyword(["c", "d", "a"]))
    hits, ms = retriever.search("x", k=4)
    assert [h.chunk_id for h in hits][:2] == ["a", "c"]  # in both lists
    both = {h.chunk_id: h.matched_by for h in hits}
    assert both["a"] == ["keyword", "semantic"] and both["b"] == ["semantic"]
    assert both["d"] == ["keyword"]
    assert all(h.retrieval_mode == "hybrid" for h in hits) and retriever.mode == "hybrid"
    assert ms == 7 and len(hits) == 4


def test_hybrid_returns_keyword_hits_and_says_so_when_the_provider_refuses() -> None:
    retriever = HybridRetriever(Broken(), Keyword(["k1", "k2"]))
    hits, _ = retriever.search("x", k=5)
    assert [h.chunk_id for h in hits] == ["k1", "k2"]
    assert all(h.retrieval_mode == "keyword" for h in hits)
    assert retriever.mode == "keyword" and retriever.requested == "hybrid"
    assert retriever.fallback_reason == "Meaning-based search was unavailable: Refused (HTTP 403)"
    assert "secret body" not in retriever.fallback_reason


def test_describe_failure_reports_type_and_status_only() -> None:
    assert describe_failure(RuntimeError("secret")) == (
        "Meaning-based search was unavailable: RuntimeError"
    )


def test_vector_reuses_a_query_and_distinguishes_embedding_from_rpc_failure(monkeypatch) -> None:
    calls = []
    categories = []

    def lookup(_db, *, category, **_params):
        categories.append(category)
        if category == "materia_medica":
            try:
                raise Refused("private provider payload")
            except Refused as exc:
                raise knowledge_db.KnowledgeDBError("private DB body") from exc
        return []

    monkeypatch.setattr(knowledge_db, "search_chunks", lookup)
    vector = VectorRetriever(
        object(), SimpleNamespace(embed_query=lambda query: calls.append(query) or [1.0]),
    )
    assert vector.search("fixture", category="repertory")[0] == []
    with pytest.raises(SemanticSearchError) as error:
        vector.search("fixture", category="materia_medica")
    assert calls == ["fixture"]
    assert categories == ["repertory", "materia_medica"]
    assert describe_failure(error.value) == "Supabase vector search failed (Refused, HTTP 403)"
    assert "private" not in describe_failure(error.value)

    def embedding_fails(_query):
        raise Refused("secret request body")

    vector = VectorRetriever(object(), SimpleNamespace(embed_query=embedding_fails))
    with pytest.raises(SemanticSearchError) as error:
        vector.search("fixture")
    assert describe_failure(error.value) == (
        "Voyage denied access to query embeddings (Refused, HTTP 403)"
    )


def test_the_builder_returns_the_right_retriever_for_each_mode() -> None:
    def never():
        raise AssertionError("no provider expected")

    assert isinstance(build_retriever("keyword", object(), never), KeywordRetriever)
    stopped = build_retriever("hybrid", object(), never, paused=True)
    assert isinstance(stopped, KeywordRetriever) and stopped.requested == "hybrid"
    assert "provider stop" in stopped.fallback_reason
    built = build_retriever("hybrid", object(), lambda: object())
    assert built.requested == "hybrid" and built.mode == "hybrid"
    assert build_retriever("semantic", object(), lambda: object()).requested == "semantic"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(knowledge, "_require_db_config", lambda: None)
    monkeypatch.setattr(knowledge, "get_supabase_admin_client", lambda: object())
    monkeypatch.setattr(knowledge, "embedding_paused", lambda: False)
    monkeypatch.setattr(knowledge, "get_embedding_provider", lambda: object())
    monkeypatch.setattr(knowledge.knowledge_db, "save_retrieval_evaluation", lambda *_a: None)
    monkeypatch.setattr(knowledge, "book_completeness", lambda _db: {"b1": True})
    monkeypatch.setattr(
        knowledge.knowledge_db,
        "keyword_search_chunks",
        lambda _db, tsquery, match_count, category=None: [
            {
                "chunk_id": "k1",
                "book_id": "b1",
                "section_id": None,
                "book_title": "MM",
                "book_category": "materia_medica",
                "book_author": None,
                "section_heading": "H",
                "section_path": [],
                "content": "x",
                "similarity": 0.3,
                "chunk_metadata": {},
            }
        ],
    )
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "operator"
    return TestClient(app)


def use_semantic(monkeypatch: pytest.MonkeyPatch, cls) -> None:
    monkeypatch.setattr("app.ai.rag.retrieval.VectorRetriever", cls)


class VectorWorks:
    def __init__(self, **_k) -> None: ...

    def search(self, *_a, **_k):
        return [hit("v1", "semantic", 0.8)], 3


class VectorRefused:
    def __init__(self, **_k) -> None: ...

    def search(self, *_a, **_k):
        raise Refused("403")


def post(client, mode: str) -> dict:
    response = client.post("/api/search", json={"query": "burning pain", "mode": mode})
    assert response.status_code == 200, response.text
    return response.json()


def test_search_semantic_keyword_and_hybrid_each_report_the_method_that_ran(
    client, monkeypatch
) -> None:
    use_semantic(monkeypatch, VectorWorks)
    semantic = post(client, "semantic")
    assert semantic["retrieval_mode"] == "semantic" and semantic["requested_mode"] == "semantic"
    assert semantic["fallback_reason"] is None
    keyword = post(client, "keyword")
    assert keyword["retrieval_mode"] == "keyword" and keyword["results"][0]["chunk_id"] == "k1"
    hybrid = post(client, "hybrid")
    assert hybrid["retrieval_mode"] == "hybrid"
    assert {r["chunk_id"] for r in hybrid["results"]} == {"v1", "k1"}
    assert all(r["retrieval_mode"] == "hybrid" for r in hybrid["results"])


def test_a_refused_provider_still_answers_and_reports_the_403(client, monkeypatch) -> None:
    use_semantic(monkeypatch, VectorRefused)
    for mode in ("semantic", "hybrid"):
        body = post(client, mode)
        assert body["requested_mode"] == mode and body["retrieval_mode"] == "keyword"
        assert "HTTP 403" in body["fallback_reason"]
        assert body["results"][0]["retrieval_mode"] == "keyword"


def test_an_unknown_mode_is_rejected(client) -> None:
    response = client.post("/api/search", json={"query": "x", "mode": "magic"})
    assert response.status_code == 422


def test_the_provider_stop_forces_keyword_and_says_why(client, monkeypatch) -> None:
    monkeypatch.setattr(knowledge, "embedding_paused", lambda: True)

    def forbidden(**_k):
        raise AssertionError("no provider while the stop is set")

    monkeypatch.setattr(knowledge, "get_embedding_provider", forbidden)
    body = post(client, "hybrid")
    assert body["retrieval_mode"] == "keyword" and "provider stop" in body["fallback_reason"]


def test_the_analysis_output_reports_requested_and_actual_method() -> None:
    from uuid import uuid4

    from app.api.routes import cases as cases_routes

    base = {
        "id": str(uuid4()),
        "case_id": str(uuid4()),
        "outcome": "ranked",
        "created_at": "2026-11-24T10:00:00+00:00",
    }

    def p(mode: str, requested: str, reason=None) -> dict:
        return {
            "chunk_id": mode,
            "book_title": "B",
            "book_category": "organon",
            "content": "x",
            "similarity": 0.3,
            "retrieval_mode": mode,
            "requested_mode": requested,
            "fallback_reason": reason,
            "matched_by": [mode],
        }

    out = cases_routes._analysis_out(
        {**base, "passages": [p("keyword", "hybrid", "Meaning-based search was unavailable")]}
    )
    assert (out.retrieval_mode, out.requested_mode) == ("keyword", "hybrid")
    assert "unavailable" in out.fallback_reason
    hybrid = cases_routes._analysis_out({**base, "passages": [p("hybrid", "hybrid")]})
    assert hybrid.retrieval_mode == "hybrid" and hybrid.fallback_reason is None
    historical = cases_routes._analysis_out({**base, "passages": []})
    assert (historical.requested_mode, historical.retrieval_mode) == ("unknown", "unknown")
    new = cases_routes._analysis_out({
        **base, "passages": [], "queries": {
            "phrases": ["fixture"],
            "retrieval": {
                "requested_mode": "semantic", "retrieval_mode": "keyword",
                "fallback_reason": "Voyage unavailable",
            },
        },
    })
    assert (new.requested_mode, new.retrieval_mode) == ("semantic", "keyword")
    assert new.fallback_reason == "Voyage unavailable"


def test_search_keeps_results_when_coverage_or_evaluation_is_unavailable(client, monkeypatch):
    use_semantic(monkeypatch, VectorWorks)

    def unavailable(*_args):
        raise knowledge_db.KnowledgeDBError("private error")

    monkeypatch.setattr(knowledge, "book_completeness", unavailable)
    monkeypatch.setattr(knowledge.knowledge_db, "save_retrieval_evaluation", unavailable)
    result = post(client, "semantic")
    assert result["retrieval_mode"] == "semantic"
    assert result["results"][0]["chunk_id"] == "v1"
    assert result["results"][0]["book_complete"] is False


def test_the_analyzer_records_the_method_in_every_saved_passage() -> None:
    from app.ai.rag.case_analysis import (
        CaseAnalyzer,
        NormalisedCase,
        RankedOutput,
        RankedRemedy,
        SearchQuery,
    )
    from tests.test_case_analysis import FakeReasoner

    retriever = HybridRetriever(Broken(), Keyword(["k1"]))
    reasoner = FakeReasoner(
        NormalisedCase(queries=[SearchQuery(text="itch")]),
        RankedOutput(
            remedies=[RankedRemedy(remedy="R", confidence="low", rationale="r", citations=["P1"])]
        ),
    )
    case = {"chief_complaint": "itch", "language": "en", "symptoms": []}
    result = CaseAnalyzer(retriever, reasoner).analyze(case)
    saved = result.passages[0]
    assert saved["retrieval_mode"] == "keyword" and saved["requested_mode"] == "hybrid"
    assert saved["matched_by"] == ["keyword"] and "HTTP 403" in saved["fallback_reason"]
