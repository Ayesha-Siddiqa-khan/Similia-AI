"""Dataset quality and preparation report."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from app.ai.finetune.config import (
    MODULE_VERSION,
    PILOT_TARGET,
    POLICY_VERSION,
    SCIENTIFIC_BOUNDARY,
)
from app.ai.finetune.dedupe import DuplicateGroup
from app.ai.finetune.models import BookRecord, CleanChunk, SplitAssignment
from app.ai.finetune.pilot import PilotResult


def _book_stats(clean_chunks: list[CleanChunk]) -> list[dict[str, Any]]:
    grouped: dict[str, list[CleanChunk]] = defaultdict(list)
    for clean in clean_chunks:
        grouped[clean.book.id].append(clean)
    rows: list[dict[str, Any]] = []
    for book_id, chunks in grouped.items():
        book = chunks[0].book
        usable = [chunk for chunk in chunks if chunk.usable]
        rows.append(
            {
                "book_id": book_id,
                "title": book.title,
                "author": book.author,
                "category": book.category,
                "chunks_read": len(chunks),
                "chunks_usable": len(usable),
                "chunks_duplicate": sum(1 for chunk in chunks if chunk.duplicate_of),
                "chunks_quality_failed": sum(1 for chunk in chunks if not chunk.quality.usable),
                "characters_usable": sum(len(chunk.text) for chunk in usable),
                "tokens_usable": sum(max(1, len(chunk.text) // 4) for chunk in usable),
            }
        )
    return sorted(rows, key=lambda row: row["tokens_usable"], reverse=True)


def build_report(
    *,
    books: list[BookRecord],
    exportable: list[BookRecord],
    blocked: list[BookRecord],
    suppressed: list[BookRecord],
    quality_excluded: list[BookRecord],
    clean_chunks: list[CleanChunk],
    duplicate_groups: list[DuplicateGroup],
    assignments: list[SplitAssignment],
    cpt_by_split: dict[str, list[dict[str, Any]]],
    pilot: PilotResult,
    files: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    usable = [clean for clean in clean_chunks if clean.usable]
    removed = Counter(kind for clean in clean_chunks for kind in clean.removed)
    issues = Counter(issue for clean in clean_chunks for issue in clean.quality.issues)
    duplicate_kinds = Counter(group.kind for group in duplicate_groups)
    duplicate_members = sum(len(group.members) - 1 for group in duplicate_groups)

    split_by_book = {assignment.book_id: assignment.split for assignment in assignments}
    split_stats: dict[str, dict[str, Any]] = {
        "train": {"books": 0, "chunks": 0, "characters": 0, "tokens": 0},
        "validation": {"books": 0, "chunks": 0, "characters": 0, "tokens": 0},
        "test": {"books": 0, "chunks": 0, "characters": 0, "tokens": 0},
    }
    seen_books: dict[str, set[str]] = defaultdict(set)
    for clean in usable:
        split = split_by_book.get(clean.book.id)
        if split is None:
            continue
        stats = split_stats[split]
        seen_books[split].add(clean.book.id)
        stats["chunks"] += 1
        stats["characters"] += len(clean.text)
        stats["tokens"] += max(1, len(clean.text) // 4)
    for split, ids in seen_books.items():
        split_stats[split]["books"] = len(ids)

    question_types = Counter(
        example["metadata"]["question_type"] for example in pilot.examples
    )
    answer_lengths = [
        len(example["metadata"]["answer_quote"]) for example in pilot.examples
    ]
    evidence_classes = Counter(
        example["metadata"]["evidence"]["evidence_class"] for example in pilot.examples
    )
    scientific_status = Counter(
        example["metadata"]["evidence"]["scientific_status"] for example in pilot.examples
    )

    titles = {book.id: book.title for book in books}
    pilot_per_book = {
        titles.get(book_id, book_id): count for book_id, count in sorted(pilot.per_book.items())
    }

    metadata_gaps = {
        "books_missing_author": sum(1 for book in books if not book.author),
        "books_missing_publisher": sum(1 for book in books if not book.publisher),
        "books_missing_publication_year": sum(1 for book in books if not book.publication_year),
        "books_missing_source_uri": sum(1 for book in books if not book.source_uri),
        "chunks_missing_section_id": sum(
            1 for clean in clean_chunks if clean.chunk.section_id is None
        ),
        "chunks_missing_source_char_start": sum(
            1 for clean in clean_chunks if clean.chunk.metadata.get("source_char_start") is None
        ),
    }

    cpt_stats = {}
    for split, documents in cpt_by_split.items():
        cpt_stats[split] = {
            "documents": len(documents),
            "characters": sum(document["characters"] for document in documents),
            "tokens": sum(document["token_estimate"] for document in documents),
        }

    verified = pilot.verification.get("passed", 0)
    verdict = (
        "ready_for_internal_sft_pilot"
        if len(pilot.examples) >= PILOT_TARGET and pilot.verification.get("failed", 0) == 0
        else "incomplete"
    )

    return {
        "module_version": MODULE_VERSION,
        "policy_version": POLICY_VERSION,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "verdict": verdict,
        "corpus": {
            "books_in_database": len(books),
            "books_read": len({clean.book.id for clean in clean_chunks}),
            "chunks_read": len(clean_chunks),
            "chunks_usable": len(usable),
            "characters_usable": sum(len(clean.text) for clean in usable),
            "tokens_usable": sum(max(1, len(clean.text) // 4) for clean in usable),
            "chunks_duplicate": sum(1 for clean in clean_chunks if clean.duplicate_of),
            "chunks_quality_failed": sum(1 for clean in clean_chunks if not clean.quality.usable),
        },
        "licences": {
            "exportable": len(exportable),
            "blocked": len(blocked),
            "suppressed": len(suppressed),
            "quality_excluded": len(quality_excluded),
            "exportable_titles": [book.title for book in exportable],
            "blocked_titles": [book.title for book in blocked],
            "suppressed_titles": [book.title for book in suppressed],
            "quality_excluded_titles": [book.title for book in quality_excluded],
        },
        "cleaning": {
            "artefacts_removed": dict(sorted(removed.items())),
            "quality_issues": dict(sorted(issues.items())),
            "chunks_with_any_artefact": sum(1 for clean in clean_chunks if clean.removed),
        },
        "duplicates": {
            "groups": len(duplicate_groups),
            "by_kind": dict(sorted(duplicate_kinds.items())),
            "redundant_chunks": duplicate_members,
            "largest_groups": [
                {
                    "kind": group.kind,
                    "members": len(group.members),
                    "representative": group.representative,
                }
                for group in sorted(
                    duplicate_groups, key=lambda item: len(item.members), reverse=True
                )[:10]
            ],
        },
        "splits": split_stats,
        "cpt": cpt_stats,
        "sft": {
            "target": PILOT_TARGET,
            "examples": len(pilot.examples),
            "verified": verified,
            "failed": pilot.verification.get("failed", 0),
            "failure_reasons": pilot.verification.get("failure_reasons", {}),
            "candidates": pilot.candidates,
            "shortfall": pilot.shortfall,
            "per_book": pilot_per_book,
            "question_types": dict(sorted(question_types.items())),
            "answer_characters": {
                "min": min(answer_lengths) if answer_lengths else 0,
                "median": statistics.median(answer_lengths) if answer_lengths else 0,
                "max": max(answer_lengths) if answer_lengths else 0,
            },
            "evidence_classes": dict(sorted(evidence_classes.items())),
            "scientific_status": dict(sorted(scientific_status.items())),
        },
        "per_book": _book_stats(clean_chunks),
        "metadata_gaps": metadata_gaps,
        "files": files,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def render_markdown(report: dict[str, Any]) -> str:
    corpus = report["corpus"]
    licences = report["licences"]
    duplicates = report["duplicates"]
    splits = report["splits"]
    cpt = report["cpt"]
    sft = report["sft"]
    gaps = report["metadata_gaps"]

    lines: list[str] = [
        "# Fine-tuning dataset preparation report",
        "",
        f"Module `{report['module_version']}` under licence policy `{report['policy_version']}`.",
        f"Elapsed: {report['elapsed_seconds']} s. Verdict: **{report['verdict']}**.",
        "",
        "## 1. Licence gate",
        "",
        "| Decision | Books |",
        "|---|---:|",
        f"| Exportable (public-domain basis) | {licences['exportable']} |",
        f"| Blocked (copyright or unverified) | {licences['blocked']} |",
        f"| Suppressed duplicate | {licences['suppressed']} |",
        f"| Cleared but quality-excluded | {licences['quality_excluded']} |",
        "",
        "**Exportable titles**",
        "",
    ]
    for title in licences["exportable_titles"]:
        lines.append(f"- {title}")
    lines += ["", "**Blocked titles**", ""]
    for title in licences["blocked_titles"]:
        lines.append(f"- {title}")
    if licences["quality_excluded_titles"]:
        lines += ["", "**Cleared but not exportable**", ""]
        for title in licences["quality_excluded_titles"]:
            lines.append(f"- {title}")
    if licences["suppressed_titles"]:
        lines += ["", "**Suppressed duplicates**", ""]
        for title in licences["suppressed_titles"]:
            lines.append(f"- {title}")

    lines += [
        "",
        "## 2. Corpus and cleaning",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Books in database | {corpus['books_in_database']} |",
        f"| Books read for export | {corpus['books_read']} |",
        f"| Chunks read | {corpus['chunks_read']:,} |",
        f"| Usable chunks | {corpus['chunks_usable']:,} |",
        f"| Usable characters | {corpus['characters_usable']:,} |",
        f"| Usable tokens (chars / 4) | {corpus['tokens_usable']:,} |",
        f"| Duplicate chunks removed | {corpus['chunks_duplicate']:,} |",
        f"| Quality-failed chunks | {corpus['chunks_quality_failed']:,} |",
        f"| Chunks with an artefact removed | {report['cleaning']['chunks_with_any_artefact']:,} |",
        "",
        "**Artefacts removed**",
        "",
        "| Artefact | Chunks |",
        "|---|---:|",
    ]
    for kind, count in report["cleaning"]["artefacts_removed"].items():
        lines.append(f"| {kind} | {count:,} |")
    lines += ["", "**Quality issues**", "", "| Issue | Chunks |", "|---|---:|"]
    for issue, count in report["cleaning"]["quality_issues"].items():
        lines.append(f"| {issue} | {count:,} |")

    lines += [
        "",
        "## 3. Duplicates",
        "",
        (
            f"Groups: **{duplicates['groups']}**, "
            f"redundant chunks: **{duplicates['redundant_chunks']}**."
        ),
        "",
        "| Kind | Groups |",
        "|---|---:|",
    ]
    for kind, count in duplicates["by_kind"].items():
        lines.append(f"| {kind} | {count} |")

    lines += [
        "",
        "## 4. Book-level splits",
        "",
        "| Split | Books | Chunks | Characters | Tokens |",
        "|---|---:|---:|---:|---:|",
    ]
    for split in ("train", "validation", "test"):
        stats = splits[split]
        lines.append(
            f"| {split} | {stats['books']} | {stats['chunks']:,} | "
            f"{stats['characters']:,} | {stats['tokens']:,} |"
        )

    lines += [
        "",
        "## 5. Continued pre-training export",
        "",
        "| Split | Documents | Characters | Tokens |",
        "|---|---:|---:|---:|",
    ]
    for split in ("train", "validation", "test"):
        stats = cpt[split]
        lines.append(
            f"| {split} | {stats['documents']} | {stats['characters']:,} | {stats['tokens']:,} |"
        )

    lines += [
        "",
        "## 6. SFT pilot",
        "",
        f"Target: **{sft['target']}**, built: **{sft['examples']}**, "
        f"verified: **{sft['verified']}**, failed: **{sft['failed']}**.",
        "",
        "| Book | Examples |",
        "|---|---:|",
    ]
    for title, count in sft["per_book"].items():
        lines.append(f"| {title} | {count} |")
    lines += [
        "",
        "| Question type | Examples |",
        "|---|---:|",
    ]
    for kind, count in sft["question_types"].items():
        lines.append(f"| {kind} | {count} |")
    lines += [
        "",
        f"Answer length: min {sft['answer_characters']['min']}, "
        f"median {sft['answer_characters']['median']}, "
        f"max {sft['answer_characters']['max']} characters.",
        "",
        "## 7. Evidence boundary",
        "",
        "| Evidence class | Examples |",
        "|---|---:|",
    ]
    for name, count in sft["evidence_classes"].items():
        lines.append(f"| {name} | {count} |")
    lines += [
        "",
        "| Scientific status | Examples |",
        "|---|---:|",
    ]
    for name, count in sft["scientific_status"].items():
        lines.append(f"| {name} | {count} |")
    lines += ["", f"> {report['scientific_boundary']}", ""]

    lines += [
        "## 8. Metadata gaps",
        "",
        "| Gap | Count |",
        "|---|---:|",
    ]
    for name, count in gaps.items():
        lines.append(f"| {name} | {count} |")

    lines += [
        "",
        "## 9. Files",
        "",
        "| File | Records | Bytes | SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for item in report["files"]:
        lines.append(
            f"| `{item['path']}` | {item['records']:,} | {item['bytes']:,} | "
            f"`{item['sha256'][:16]}...` |"
        )

    lines += [
        "",
        "## 10. Limits",
        "",
        "- Clearance is an engineering public-domain assessment, not a legal opinion.",
        "- The pilot answers are verbatim extracts verified against cleaned source text; "
        "clinical review is still required before any clinical use.",
        "- No embeddings, patient records or personal information were read or exported.",
        "- No upload, dependency installation or model training was performed.",
        "",
    ]
    return "\n".join(lines)
