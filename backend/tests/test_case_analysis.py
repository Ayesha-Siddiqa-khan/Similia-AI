"""Case analysis safety properties: red-flag first, citation guard, no guessing."""

from app.ai.rag.case_analysis import (
    CaseAnalyzer,
    NormalisedCase,
    RankedOutput,
    RankedRemedy,
    SearchQuery,
    build_case_text,
    screen_red_flags,
)
from app.ai.rag.retrieval import RetrievedPassage, analysis_search_info


def passage(chunk_id: str, similarity: float = 0.8) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id,
        book_id="b1",
        section_id=None,
        book_title="Materia Medica",
        book_category="materia_medica",
        book_author=None,
        section_heading="Remedy",
        section_path=[],
        content=f"text of {chunk_id}",
        similarity=similarity,
        metadata={},
    )


class FakeRetriever:
    def __init__(self, hits: list[RetrievedPassage]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def search(self, query, k=5, category=None, threshold=0.0):
        self.queries.append(query)
        return self.hits, 1


class FakeReasoner:
    def __init__(self, normalised: NormalisedCase, ranked: RankedOutput | None = None) -> None:
        self.normalised = normalised
        self.ranked = ranked or RankedOutput()
        self.normalise_calls = 0
        self.rank_calls = 0

    def normalise(self, case_text, language):
        self.normalise_calls += 1
        return self.normalised

    def rank(self, case_text, passages):
        self.rank_calls += 1
        self.passage_ids = list(passages)
        return self.ranked


def case(complaint="headache worse in sun", **extra):
    return {"chief_complaint": complaint, "language": "en", "symptoms": [], **extra}


def remedy(name, citations):
    return RankedRemedy(remedy=name, confidence="medium", rationale="fits", citations=citations)


def test_red_flags_detected_in_english_hindi_and_urdu():
    assert screen_red_flags("severe CHEST PAIN since morning")
    assert screen_red_flags("मरीज़ को सीने में दर्द है")
    assert screen_red_flags("مریض کو خودکشی کے خیالات ہیں")
    assert screen_red_flags("mild headache after sun exposure") == []


def test_red_flag_stops_before_any_llm_or_retrieval():
    reasoner = FakeReasoner(NormalisedCase())
    retriever = FakeRetriever([passage("c1")])
    result = CaseAnalyzer(retriever, reasoner).analyze(case("crushing chest pain"))
    assert result.outcome == "red_flag" and result.red_flags
    assert reasoner.normalise_calls == 0 and retriever.queries == []


def test_llm_flagged_urgency_stops_before_retrieval():
    reasoner = FakeReasoner(NormalisedCase(urgent_concerns=["possible meningitis"]))
    retriever = FakeRetriever([passage("c1")])
    result = CaseAnalyzer(retriever, reasoner).analyze(case())
    assert result.outcome == "red_flag" and result.red_flags == ["possible meningitis"]
    assert retriever.queries == [] and reasoner.rank_calls == 0


def test_practitioner_can_acknowledge_red_flags_and_they_stay_visible():
    reasoner = FakeReasoner(
        NormalisedCase(queries=[SearchQuery(text="chest pain")]),
        RankedOutput(remedies=[remedy("Arnica", ["P1"])]),
    )
    analyzer = CaseAnalyzer(FakeRetriever([passage("c1")]), reasoner)
    result = analyzer.analyze(case("chest pain after a fall"), acknowledge_red_flags=True)
    assert result.outcome == "ranked" and result.red_flags


def test_citation_guard_drops_uncited_and_invented_remedies():
    ranked = RankedOutput(
        remedies=[
            remedy("Belladonna", ["P1", "[P2]"]),
            remedy("Invented", ["P99"]),  # not a retrieved passage
            remedy("NoCitation", []),
        ],
        missing_information=["Is the pain throbbing?"],
    )
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="headache sun")]), ranked)
    retriever = FakeRetriever([passage("c1", 0.9), passage("c2", 0.7)])
    result = CaseAnalyzer(retriever, reasoner).analyze(case())
    assert result.outcome == "ranked"
    assert [r["remedy"] for r in result.remedies] == ["Belladonna"]
    assert result.remedies[0]["citations"] == ["c1", "c2"]  # P ids mapped to chunk ids
    assert result.missing_information == ["Is the pain throbbing?"]


def test_no_supported_remedy_means_insufficient_sources_not_a_guess():
    ranked = RankedOutput(remedies=[remedy("Invented", ["P42"])])
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="x")]), ranked)
    result = CaseAnalyzer(FakeRetriever([passage("c1")]), reasoner).analyze(case())
    assert result.outcome == "insufficient_sources" and result.remedies == []


def test_no_retrieved_passages_skips_ranking():
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="x")]))
    result = CaseAnalyzer(FakeRetriever([]), reasoner).analyze(case())
    assert result.outcome == "insufficient_sources" and reasoner.rank_calls == 0


def test_late_fallback_preserves_the_semantic_passage_and_records_both_modes():
    sem, kw = passage("same", 0.75), passage("same", 999)
    kw.retrieval_mode = "keyword"

    class LateFallback:
        requested = "semantic"
        mode = "semantic"
        fallback_reason = None

        def search(self, query, **_kwargs):
            if query == "first":
                return [sem], 0
            self.mode = "keyword"
            self.fallback_reason = "Voyage temporarily unavailable"
            return [kw], 0

    reasoner = FakeReasoner(NormalisedCase(queries=[
        SearchQuery(text="first"), SearchQuery(text="first"), SearchQuery(text="second"),
    ]))
    result = CaseAnalyzer(LateFallback(), reasoner).analyze(case())
    assert result.queries == ["first", "second"]
    assert result.passages[0]["similarity"] == 0.75
    assert result.passages[0]["retrieval_mode"] == "semantic"
    assert result.retrieval == {
        "requested_mode": "semantic", "retrieval_mode": "mixed",
        "fallback_reason": "Voyage temporarily unavailable",
    }


def test_empty_fallback_and_historical_metadata_are_reported_without_guessing():
    retriever = FakeRetriever([])
    retriever.requested = "semantic"
    retriever.mode = "keyword"
    retriever.fallback_reason = "Voyage unavailable"
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="fixture")]))
    result = CaseAnalyzer(retriever, reasoner).analyze(case())
    snapshot = {
        "queries": {"phrases": result.queries, "retrieval": result.retrieval},
        "passages": [],
    }
    assert analysis_search_info(snapshot)["retrieval_mode"] == "keyword"
    assert analysis_search_info(snapshot)["fallback_reason"] == "Voyage unavailable"
    assert analysis_search_info({"queries": ["fixture"], "passages": []})["retrieval_mode"] == (
        "unknown"
    )


def test_duplicate_chunks_across_queries_are_deduplicated_and_capped():
    queries = [SearchQuery(text=f"q{i}") for i in range(12)]
    reasoner = FakeReasoner(NormalisedCase(queries=queries))
    retriever = FakeRetriever([passage("c1")])
    result = CaseAnalyzer(retriever, reasoner).analyze(case())
    assert len(retriever.queries) == 5  # Four primary concepts plus a thin-evidence follow-up.
    assert len(reasoner.passage_ids) == 1 and len(result.passages) == 1


def test_case_text_includes_modalities_and_kind():
    text = build_case_text(
        case(
            symptoms=[{"kind": "mental", "label": "Irritable", "worse": "consolation", "weight": 3}]
        )
    )
    assert "[mental, weight 3]" in text and "worse with: consolation" in text


def test_weak_matches_below_the_minimum_similarity_are_not_evidence():
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="x")]))
    retriever = FakeRetriever([passage("weak", 0.1)])
    result = CaseAnalyzer(retriever, reasoner, min_similarity=0.25).analyze(case())
    assert result.outcome == "insufficient_sources" and reasoner.rank_calls == 0


def test_passages_carry_source_details_and_partial_index_flag():
    hit = passage("c1")
    hit.book_author = "S. Hahnemann"
    hit.section_path = ["Part 1", "Aphorism 3"]
    hit.metadata = {"page_start": 12, "page_end": 13}
    other = passage("c2")
    other.book_id = "b2"
    ranked = RankedOutput(remedies=[remedy("Belladonna", ["P1"])])
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="x")]), ranked)
    analyzer = CaseAnalyzer(
        FakeRetriever([hit, other]), reasoner, completeness=lambda: {"b1": False, "b2": True}
    )
    first, second = analyzer.analyze(case()).passages
    assert first["book_author"] == "S. Hahnemann" and first["section_path"] == [
        "Part 1",
        "Aphorism 3",
    ]
    assert (first["page_start"], first["page_end"]) == (12, 13) and first["book_complete"] is False
    assert second["page_start"] is None and second["book_complete"] is True  # never guessed


def test_unknown_completeness_counts_as_partial_when_stats_are_available():
    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="x")]))
    analyzer = CaseAnalyzer(FakeRetriever([passage("c1")]), reasoner, completeness=lambda: {})
    assert analyzer.analyze(case()).passages[0]["book_complete"] is False
