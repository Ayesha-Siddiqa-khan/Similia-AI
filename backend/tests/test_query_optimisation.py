from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from voyageai.error import RateLimitError

from app.ai.rag.case_analysis import CaseAnalyzer, NormalisedCase, SearchQuery, plan_queries
from app.ai.rag.retrieval import VectorRetriever, supports_query
from app.services import knowledge_db
from app.services.voyage_budget import VoyageBudget, VoyageBudgetUnavailable
from tests.test_case_analysis import FakeReasoner, FakeRetriever, case, passage
from tests.test_embeddings import StubVoyageClient, make_provider


def test_batch_and_repeated_search_reduce_requests_without_cross_practitioner_cache():
    queries = [
        "weeping eczema with sticky discharge", "itching worse as the bed warms",
        "winter eruption relieved in open air",
    ]
    old_client = StubVoyageClient()
    old = make_provider(old_client)
    previous = {query: old.embed_query(query) for query in queries}

    client = StubVoyageClient()
    provider = make_provider(client)
    owner = str(uuid4())
    new = provider.embed_queries([*queries, queries[0]], scope=owner)
    assert new.keys() == previous.keys()
    assert len(old_client.calls) == 3
    assert [call["texts"] for call in client.calls] == [queries]
    assert old.total_tokens_used == provider.total_tokens_used
    assert provider.embed_queries(queries, scope=owner) == new
    assert len(client.calls) == 1
    provider.embed_queries(queries, scope=str(uuid4()))
    assert len(client.calls) == 2


def test_multiple_workers_share_request_and_token_reservations(tmp_path):
    db = tmp_path / "budget.sqlite"
    a, b = VoyageBudget(db, 2, 10), VoyageBudget(db, 2, 10)
    a.reserve(6, max_wait=0)  # ingestion

    def reserve(limiter):
        try:
            limiter.reserve(4, max_wait=0)
            return True
        except VoyageBudgetUnavailable:
            return False

    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(reserve, [a, b])) == [False, True]
    with pytest.raises(VoyageBudgetUnavailable):
        b.reserve(1, max_wait=0)


def test_shared_wait_can_be_cancelled_before_spending(tmp_path):
    limiter = VoyageBudget(tmp_path / "budget.sqlite", 1, 10)
    with pytest.raises(VoyageBudgetUnavailable):
        limiter.reserve(1, max_wait=10, cancelled=lambda: True)
    assert limiter.reserve(10, max_wait=0)


def test_query_plan_removes_duplicates_and_contact_details_but_keeps_contradictions():
    findings = NormalisedCase(
        queries=[
            SearchQuery(text="Itching worse in bed", concept="warm-bed", weight=3),
            SearchQuery(text="Itching aggravated in a warm bed", concept="warm-bed"),
            SearchQuery(text="Itching better in bed", concept="warm-bed"),
            SearchQuery(text="person@example.com itchy skin"),
            SearchQuery(text="Exampleperson itching in bed"),
        ],
        negative_findings=["No change outdoors"],
        uncertain_information=["Whether the warmth or bedding triggers symptoms"],
        urgent_concerns=["Urgency reviewed from full case"],
    )
    primary, follow_up = plan_queries(findings, ("Exampleperson",))
    assert primary + follow_up == ["Itching worse in bed", "Itching better in bed"]
    assert findings.negative_findings == ["No change outdoors"]
    assert findings.urgent_concerns


def test_topic_screen_filters_incidental_matches_but_keeps_strong_paraphrases():
    query = "Weeping eczema with sticky discharge worse in winter"
    good = passage("good", 0.57)
    good.content = "Eczematous patches exuded fluid."
    incidental = passage("incidental", 0.54)
    incidental.content = "Constipation worse in winter. Sticky eyelids in the morning."
    paraphrase = passage("paraphrase", 0.70)
    paraphrase.content = "Moist dermatitis along inflamed patches."
    assert [source.chunk_id for source in (good, incidental, paraphrase)
            if supports_query(query, source)] == ["good", "paraphrase"]


def test_batch_uses_one_slot_on_a_mock_three_request_tier():
    def capped_client():
        client = StubVoyageClient()
        send = client.embed

        def limited(*args, **kwargs):
            if len(client.calls) == 3:
                raise RateLimitError("short request window", http_status=429)
            return send(*args, **kwargs)

        client.embed = limited
        provider = make_provider(client)
        provider.max_attempts = 1
        return provider

    terms = ["first concept", "second concept", "third concept", "fourth concept"]
    baseline = capped_client()
    for query in terms[:3]:
        baseline.embed_query(query)
    with pytest.raises(RateLimitError):
        baseline.embed_query(terms[3])
    assert len(capped_client().embed_queries(terms)) == 4


def test_urdu_red_flag_stops_before_query_batch():
    class NoEmbedding(FakeRetriever):
        def prepare_queries(self, *_args):
            raise AssertionError("Urgency must be checked before embedding")

    reasoner = FakeReasoner(NormalisedCase(queries=[SearchQuery(text="fixture")]))
    result = CaseAnalyzer(NoEmbedding([]), reasoner).analyze(
        case("مریض کو خودکشی کے خیالات ہیں", language="ur"),
    )
    assert result.outcome == "red_flag"
    assert reasoner.normalise_calls == 0


def test_case_batch_preserves_full_history_for_assessment(monkeypatch):
    def retrieval(*_args, **_kwargs):
        return [
            {
                "chunk_id": key, "book_id": "synthetic", "book_title": "Fixture book",
                "book_category": "materia_medica", "content": "Skin irritation at night",
                "similarity": 0.8, "chunk_metadata": {"page_start": page},
            }
            for key, page in (("fixture-1", 3), ("fixture-2", 4))
        ]

    monkeypatch.setattr(knowledge_db, "search_chunks", retrieval)
    patient_case = case(
        "خارش رات میں زیادہ ہوتی ہے", language="ur",
        symptoms=[
            {"kind": "history", "label": "Prior treatment noted", "notes": "No improvement"},
            {"kind": "physical_general", "label": "Relieved outdoors"},
        ],
    )
    plan = NormalisedCase(queries=[
        SearchQuery(text="night skin itching"), SearchQuery(text="eruption relieved outdoors"),
    ])

    class Reasoner(FakeReasoner):
        def rank(self, case_text, passages):
            assert all(fact in case_text for fact in (
                "خارش رات میں زیادہ ہوتی ہے", "Prior treatment noted", "No improvement",
                "Relieved outdoors",
            ))
            return super().rank(case_text, passages)

    client = StubVoyageClient()
    vector = VectorRetriever(object(), make_provider(client))
    result = CaseAnalyzer(vector, Reasoner(plan), cache_scope=str(uuid4())).analyze(patient_case)
    assert [call["texts"] for call in client.calls] == [[q.text for q in plan.queries]]
    assert result.retrieval["retrieval_mode"] == "semantic"
    assert [source["page_start"] for source in result.passages] == [3, 4]
