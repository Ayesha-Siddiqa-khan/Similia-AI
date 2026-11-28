"""Compare search modes on the EXISTING case. Read-only; no model call; no re-embedding.

What it does
- Finds the existing case (or use --case-id) and its latest saved analysis. It reuses the search
  phrases already saved with that analysis, so the case text is NOT sent anywhere again.
- Runs keyword search for those phrases and compares it with what the saved analysis used.
- Checks the saved analysis: do citations resolve, are the stated fits/against backed by the
  cited passages (a lexical heuristic, not clinical validation).
- Semantic and hybrid need the embedding provider. They run ONLY with --live-voyage, which
  sends the saved search phrases (not the case text, not patient data) to the provider.
  It makes one probe first and stops at the first failure, so an Atlas HTTP 403 is reported,
  never bypassed.

It writes nothing to the database. Its report holds no patient name, ID, contact or symptom
wording. Save it with --out (use reports/evaluation/, which is git-ignored).

    uv run python scripts/evaluate_search_modes.py
    uv run python scripts/evaluate_search_modes.py --live-voyage     # needs your approval
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.evaluation.search_modes import (  # noqa: E402
    check_citations,
    describe_passages,
    merge_query_hits,
    overlap,
    passage_ids,
)
from app.ai.rag.case_analysis import MAX_PASSAGES, PER_QUERY_K  # noqa: E402
from app.ai.rag.coverage import book_completeness  # noqa: E402
from app.ai.rag.retrieval import (  # noqa: E402
    HybridRetriever,
    KeywordRetriever,
    VectorRetriever,
    analysis_search_info,
    describe_failure,
)
from app.services.embeddings import get_embedding_provider  # noqa: E402
from app.services.supabase import get_supabase_admin_client  # noqa: E402


def pick_case(db, case_id: str | None) -> tuple[dict, dict]:
    cases = db.table("cases").select("id,status,updated_at").execute().data
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
    candidates = []
    for case in cases:
        rows = (
            db.table("case_analyses")
            .select("*")
            .eq("case_id", case["id"])
            .eq("outcome", "ranked")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            candidates.append((case, rows[0]))
    if len(candidates) != 1:
        ids = [c["id"] for c, _ in candidates]
        raise SystemExit(
            f"Expected exactly one case with a ranked analysis; found {ids}. Pass --case-id."
        )
    return candidates[0]


def summarise(name: str, passages: list, complete: dict) -> dict:
    rows = [
        {
            "chunk_id": p.chunk_id,
            "book_id": p.book_id,
            "book_title": p.book_title,
            "book_category": p.book_category,
            "page_start": (p.metadata or {}).get("page_start"),
        }
        for p in passages
    ]
    return {"mode": name, **describe_passages(rows, complete), "ids": passage_ids(rows)}


def run(args: argparse.Namespace) -> dict:
    db = get_supabase_admin_client()
    case, analysis = pick_case(db, args.case_id)
    saved_queries = analysis.get("queries") or []
    queries = saved_queries.get("phrases", []) if isinstance(saved_queries, dict) else saved_queries
    saved = analysis.get("passages") or []
    complete = book_completeness(db)
    report: dict = {
        "case": case["id"][:8],
        "analysis_created": analysis["created_at"],
        "saved_search_phrases": len(queries),
        "saved_analysis": {
            **analysis_search_info(analysis),
            "passages": len(saved),
            "remedies": len(analysis.get("remedies") or []),
            "red_flags_recorded": len(analysis.get("red_flags") or []),
        },
        "modes": {},
        "citations": check_citations(analysis),
    }

    keyword = KeywordRetriever(db)
    per_query = [keyword.search(q, k=PER_QUERY_K)[0] for q in queries]
    kw = merge_query_hits(per_query, MAX_PASSAGES)
    report["modes"]["keyword"] = {
        "status": "tested",
        **summarise("keyword", kw, complete),
        "vs_saved_analysis": overlap(passage_ids(saved), [p.chunk_id for p in kw]),
    }

    if not args.live_voyage:
        for mode in ("semantic", "hybrid"):
            report["modes"][mode] = {
                "status": "not run",
                "reason": "needs --live-voyage and your approval (live provider call)",
            }
        return report

    vector = VectorRetriever(db=db, embedder=get_embedding_provider(max_attempts=1))
    try:
        vector.search(queries[0] if queries else "test", k=1)  # one probe, stop on failure
    except Exception as exc:
        for mode in ("semantic", "hybrid"):
            report["modes"][mode] = {
                "status": "BLOCKED",
                "reason": describe_failure(exc),
                "note": "Reported as is. Not bypassed. Keyword matching remains the fallback.",
            }
        return report
    sem = merge_query_hits([vector.search(q, k=PER_QUERY_K)[0] for q in queries], MAX_PASSAGES)
    hybrid = HybridRetriever(vector, keyword)
    hyb = merge_query_hits([hybrid.search(q, k=PER_QUERY_K)[0] for q in queries], MAX_PASSAGES)
    report["modes"]["semantic"] = {"status": "tested", **summarise("semantic", sem, complete)}
    report["modes"]["hybrid"] = {
        "status": "tested" if hybrid.mode == "hybrid" else "fell back to keyword",
        **summarise("hybrid", hyb, complete),
    }
    ids = {
        m: [p.chunk_id for p in ps]
        for m, ps in (("keyword", kw), ("semantic", sem), ("hybrid", hyb))
    }
    report["agreement"] = {
        "keyword_vs_semantic": overlap(ids["keyword"], ids["semantic"]),
        "keyword_vs_hybrid": overlap(ids["keyword"], ids["hybrid"]),
        "semantic_vs_hybrid": overlap(ids["semantic"], ids["hybrid"]),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--case-id")
    parser.add_argument(
        "--live-voyage",
        action="store_true",
        help="also try semantic and hybrid (live provider call; needs approval)",
    )
    parser.add_argument("--out", help="write the JSON report here (e.g. reports/evaluation/x.json)")
    args = parser.parse_args()
    report = run(args)
    for mode in report["modes"].values():
        mode.pop("ids", None)  # keep the printed report short; ids stay with --out
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
