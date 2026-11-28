"""Keyword matching fallback: free, labelled, and never presented as meaning-based search."""

import pytest

from app.ai.rag.case_analysis import (
    CaseAnalyzer,
    NormalisedCase,
    RankedOutput,
    RankedRemedy,
    SearchQuery,
)
from app.ai.rag.retrieval import (
    FallbackRetriever,
    KeywordRetriever,
    RetrievedPassage,
    keyword_terms,
    to_tsquery,
)
from app.services import knowledge_db
from tests.test_case_analysis import FakeReasoner, passage


def row(chunk_id: str = "c1", score: float = 0.4) -> dict:
    return {
        "chunk_id": chunk_id,
        "book_id": "b1",
        "section_id": None,
        "book_title": "Materia Medica",
        "book_category": "materia_medica",
        "book_author": None,
        "section_heading": "Arsenicum",
        "section_path": ["Remedies"],
        "content": f"text of {chunk_id}",
        "similarity": score,
        "chunk_metadata": {"page_start": 7},
    }


def test_terms_are_plain_lowercase_words_without_stop_words_or_symbols() -> None:
    terms = keyword_terms("Burning pain, WORSE at night; relieved by warmth & the heat!! 123")
    assert terms == ["burning", "pain", "worse", "night", "relieved", "warmth", "heat"]
    assert keyword_terms("the and for") == [] and keyword_terms("") == []
    assert keyword_terms("हिंदी उर्दू") == []  # non-Latin text yields no keyword terms


def test_the_query_is_built_from_letters_only_so_it_cannot_be_malformed() -> None:
    nasty = "a'; drop table x; -- ) & ! | ( :* burning"
    query = to_tsquery(keyword_terms(nasty))
    assert query == "drop | table | burning"
    assert all(ch.isalpha() or ch in " |" for ch in query)


def test_the_term_count_is_capped() -> None:
    many = " ".join(f"word{chr(97 + i % 26)}{chr(97 + i // 26)}x" for i in range(40))
    assert len(keyword_terms(many.replace("0", "").replace("1", ""))) <= 12


def test_the_keyword_retriever_labels_every_hit_and_calls_no_provider(monkeypatch) -> None:
    seen: dict = {}

    def fake(_db, tsquery, match_count, category=None):
        seen.update(tsquery=tsquery, k=match_count, category=category)
        return [row("c1", 0.6), row("c2", 0.2)]

    monkeypatch.setattr(knowledge_db, "keyword_search_chunks", fake)
    hits, _ms = KeywordRetriever(object()).search("burning pain warmth", k=3, category="organon")
    assert [h.chunk_id for h in hits] == ["c1", "c2"]
    assert all(h.retrieval_mode == "keyword" for h in hits)
    assert hits[0].section_path == ["Remedies"] and hits[0].metadata == {"page_start": 7}
    assert seen == {"tsquery": "burning | pain | warmth", "k": 3, "category": "organon"}


def test_nothing_is_searched_when_the_query_has_no_usable_words(monkeypatch) -> None:
    def never(*_a, **_k):
        raise AssertionError("no database call expected")

    monkeypatch.setattr(knowledge_db, "keyword_search_chunks", never)
    assert KeywordRetriever(object()).search("the and", k=5)[0] == []


class Broken:
    calls = 0

    def search(self, *_a, **_k):
        Broken.calls += 1
        raise RuntimeError("403")


class Working:
    def search(self, *_a, **_k):
        return [passage("v1")], 1


class Keyword:
    def search(self, *_a, **_k):
        hit = passage("k1")
        hit.retrieval_mode = "keyword"
        return [hit], 1


def test_the_fallback_uses_meaning_search_when_it_works() -> None:
    retriever = FallbackRetriever(Working(), Keyword())
    hits, _ = retriever.search("x")
    assert hits[0].chunk_id == "v1" and retriever.mode == "semantic"


def test_the_fallback_switches_once_and_stops_calling_the_failing_provider() -> None:
    Broken.calls = 0
    retriever = FallbackRetriever(Broken(), Keyword())
    for _ in range(5):  # an analysis runs several searches
        hits, _ = retriever.search("x")
        assert hits[0].chunk_id == "k1"
    assert Broken.calls == 1 and retriever.mode == "keyword"


def analyzer(retriever, min_similarity: float = 0.25) -> CaseAnalyzer:
    reasoner = FakeReasoner(
        NormalisedCase(queries=[SearchQuery(text="itching worse at night")]),
        RankedOutput(
            remedies=[
                RankedRemedy(remedy="Sulphur", confidence="low", rationale="fits", citations=["P1"])
            ]
        ),
    )
    return CaseAnalyzer(retriever, reasoner, min_similarity=min_similarity)


def case() -> dict:
    return {"chief_complaint": "itching worse at night", "language": "en", "symptoms": []}


def test_analysis_from_keyword_hits_is_labelled_and_not_cut_by_the_cosine_threshold() -> None:
    retriever = FallbackRetriever(Broken(), Keyword())
    # Keyword scores are small numbers: the 0.25 cosine cut-off must not drop them.
    hit = passage("k1", 0.05)
    hit.retrieval_mode = "keyword"

    class Low:
        def search(self, *_a, **_k):
            return [hit], 1

    result = analyzer(FallbackRetriever(Broken(), Low())).analyze(case())
    assert result.outcome == "ranked" and result.passages[0]["retrieval_mode"] == "keyword"
    assert result.remedies[0]["citations"] == ["k1"]
    assert retriever.mode == "semantic"  # unused wrapper stays untouched


def test_semantic_hits_below_the_threshold_are_still_dropped() -> None:
    weak: RetrievedPassage = passage("v-weak", 0.1)
    assert weak.retrieval_mode == "semantic"

    class Weak:
        def search(self, *_a, **_k):
            return [weak], 1

    assert analyzer(Weak()).analyze(case()).outcome == "insufficient_sources"


def test_the_analysis_output_keeps_both_methods_in_a_mixed_snapshot() -> None:
    from uuid import uuid4

    from app.api.routes import cases as cases_routes

    base = {
        "id": str(uuid4()),
        "case_id": str(uuid4()),
        "outcome": "ranked",
        "created_at": "2026-11-24T10:00:00+00:00",
    }
    keyword = {
        "chunk_id": "a",
        "book_title": "B",
        "book_category": "organon",
        "content": "x",
        "similarity": 0.3,
        "retrieval_mode": "keyword",
    }
    semantic = {**keyword, "chunk_id": "b", "retrieval_mode": "semantic"}
    assert cases_routes._analysis_out({**base, "passages": [semantic, keyword]}).retrieval_mode == (
        "mixed"
    )
    assert cases_routes._analysis_out({**base, "passages": [semantic]}).retrieval_mode == "semantic"
    assert cases_routes._analysis_out({**base, "passages": []}).retrieval_mode == "unknown"


def test_a_provider_stop_means_keyword_search_even_for_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.api.auth import require_operator
    from app.api.routes import knowledge
    from app.main import create_app

    monkeypatch.setattr(knowledge, "_require_db_config", lambda: None)
    monkeypatch.setattr(knowledge, "get_supabase_admin_client", lambda: object())
    monkeypatch.setattr(knowledge, "embedding_paused", lambda: False)
    monkeypatch.setattr(knowledge.knowledge_db, "save_retrieval_evaluation", lambda *_a: None)
    monkeypatch.setattr(knowledge, "book_completeness", lambda _db: {"b1": True})
    monkeypatch.setattr(
        knowledge.knowledge_db,
        "keyword_search_chunks",
        lambda _db, tsquery, match_count, category=None: [row("c9", 0.5)],
    )

    class Refused:
        def __init__(self, **_k) -> None: ...

        def search(self, *_a, **_k):
            raise RuntimeError("403 Forbidden")

    monkeypatch.setattr("app.ai.rag.retrieval.VectorRetriever", Refused)
    monkeypatch.setattr(knowledge, "get_embedding_provider", lambda: object())
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "operator"
    body = TestClient(app).post("/api/search", json={"query": "burning pain"}).json()
    assert body["retrieval_mode"] == "keyword"
    hit = body["results"][0]
    assert hit["retrieval_mode"] == "keyword" and hit["page_start"] == 7
