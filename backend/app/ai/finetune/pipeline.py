"""End-to-end dataset preparation pipeline.

The pipeline is read-only against Supabase and writes only to the local
``datasets/finetune`` folder. It never calls an LLM, an embedding provider or a
training framework.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ai.finetune.cleaning import clean_chunk_text, score_text
from app.ai.finetune.config import (
    DATASET_ROOT,
    MIN_CPT_CHARS,
    MODULE_VERSION,
    PILOT_TARGET,
    POLICY_VERSION,
)
from app.ai.finetune.cpt import build_cpt_documents
from app.ai.finetune.dedupe import find_duplicates
from app.ai.finetune.licensing import decision_for, partition_books
from app.ai.finetune.models import CleanChunk, SectionRecord
from app.ai.finetune.pilot import build_pilot
from app.ai.finetune.quality import build_report, render_markdown
from app.ai.finetune.reader import ReadOnlyKnowledgeReader
from app.ai.finetune.sft import write_jsonl
from app.ai.finetune.splits import assign_splits, split_manifest


def _load_clean_chunks(reader: ReadOnlyKnowledgeReader, books) -> list[CleanChunk]:
    clean_chunks: list[CleanChunk] = []
    for book in books:
        sections: dict[str, SectionRecord] = {
            section.id: section for section in reader.sections_for_book(book.id)
        }
        for chunk in reader.chunks_for_book(book.id):
            result = clean_chunk_text(chunk.content)
            quality = score_text(result.text, min_chars=MIN_CPT_CHARS, min_words=12)
            clean_chunks.append(
                CleanChunk(
                    chunk=chunk,
                    book=book,
                    section=sections.get(chunk.section_id) if chunk.section_id else None,
                    text=result.text,
                    removed=result.removed,
                    quality=quality,
                )
            )
    return clean_chunks


def _apply_duplicates(clean_chunks: list[CleanChunk]) -> tuple[list[CleanChunk], list]:
    items = [(clean.chunk.id, clean.text) for clean in clean_chunks if clean.text]
    groups, assigned = find_duplicates(items)
    resolved = [
        replace(
            clean,
            duplicate_of=assigned.get(clean.chunk.id, (None, None))[0],
            duplicate_kind=assigned.get(clean.chunk.id, (None, None))[1],
        )
        for clean in clean_chunks
    ]
    return resolved, groups


def run_export(
    *,
    output_dir: Path | None = None,
    target: int = PILOT_TARGET,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prepare CPT and SFT datasets and write the quality report."""
    started = time.perf_counter()
    from supabase import create_client

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError("Supabase URL and secret key are required for a read-only export")

    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    reader = ReadOnlyKnowledgeReader(client)

    books = reader.books()
    exportable, blocked, suppressed, quality_excluded = partition_books(books)
    if not exportable:
        raise RuntimeError("No exportable books: the licence gate blocked every source")

    clean_chunks = _load_clean_chunks(reader, exportable)
    clean_chunks, duplicate_groups = _apply_duplicates(clean_chunks)

    assignments = assign_splits(exportable)
    licences = {book.content_hash: decision_for(book.content_hash) for book in exportable}

    cpt_by_split = build_cpt_documents(clean_chunks, assignments, licences)
    pilot = build_pilot(clean_chunks, licences, target=target)

    output_dir = output_dir or (DATASET_ROOT / "v1")
    files: list[dict[str, Any]] = []

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for split in ("train", "validation", "test"):
            result = write_jsonl(output_dir / "cpt" / f"{split}.jsonl", cpt_by_split[split])
            files.append({**result, "kind": "cpt", "split": split})

        result = write_jsonl(output_dir / "sft" / "pilot.jsonl", pilot.examples)
        files.append({**result, "kind": "sft", "split": "pilot"})

        _write_json(
            output_dir / "sft" / "pilot_manifest.json",
            {
                "module_version": MODULE_VERSION,
                "policy_version": POLICY_VERSION,
                "target": target,
                "examples": len(pilot.examples),
                "verification": pilot.verification,
                "per_book": pilot.per_book,
                "candidates": pilot.candidates,
                "shortfall": pilot.shortfall,
                "review_status": "automated_verification_passed; clinical_review_pending",
            },
        )
        _write_json(output_dir / "splits.json", split_manifest(assignments))
        _write_json(
            output_dir / "licence_decisions.json",
            {
                "policy_version": POLICY_VERSION,
                "exportable": [
                    {"title": book.title, **licences[book.content_hash].to_dict()}
                    for book in exportable
                ],
                "blocked": [book.title for book in blocked],
                "suppressed": [book.title for book in suppressed],
                "quality_excluded": [book.title for book in quality_excluded],
            },
        )

    report = build_report(
        books=books,
        exportable=exportable,
        blocked=blocked,
        suppressed=suppressed,
        quality_excluded=quality_excluded,
        clean_chunks=clean_chunks,
        duplicate_groups=duplicate_groups,
        assignments=assignments,
        cpt_by_split=cpt_by_split,
        pilot=pilot,
        files=files,
        elapsed_seconds=time.perf_counter() - started,
    )

    if not dry_run:
        report_path = output_dir / "reports" / "quality.json"
        _write_json(report_path, report)
        markdown_path = output_dir / "reports" / "quality.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
        _write_json(
            output_dir / "manifest.json",
            {
                "module_version": MODULE_VERSION,
                "policy_version": POLICY_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(output_dir),
                "counts": {
                    "books_read": len(books),
                    "books_exportable": len(exportable),
                    "cpt_documents": sum(len(documents) for documents in cpt_by_split.values()),
                    "sft_examples": len(pilot.examples),
                },
                "files": files,
                "report": str(report_path),
                "markdown": str(markdown_path),
                "notes": [
                    "Generated locally; never uploaded.",
                    "No embeddings, patient data or personal information included.",
                    "Clinical review of the SFT pilot is pending.",
                ],
            },
        )

    return report


def verify_export(output_dir: Path) -> dict[str, Any]:
    """Re-check every pilot answer against the live, cleaned source chunks."""
    from supabase import create_client

    from app.core.config import get_settings

    pilot_path = output_dir / "sft" / "pilot.jsonl"
    if not pilot_path.exists():
        raise FileNotFoundError(f"Pilot file not found: {pilot_path}")

    examples = [
        json.loads(line)
        for line in pilot_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    reader = ReadOnlyKnowledgeReader(client)

    chunks_by_book: dict[str, dict[int, str]] = {}
    for example in examples:
        book_id = example["metadata"]["source"]["book_id"]
        if book_id not in chunks_by_book:
            chunks_by_book[book_id] = {
                chunk.chunk_index: clean_chunk_text(chunk.content).text
                for chunk in reader.chunks_for_book(book_id)
            }

    failures: list[dict[str, Any]] = []
    for example in examples:
        metadata = example["metadata"]
        book_id = metadata["source"]["book_id"]
        chunk_index = metadata["citation"]["chunk_index"]
        quote = " ".join(metadata["answer_quote"].split())
        source = " ".join(chunks_by_book.get(book_id, {}).get(chunk_index, "").split())
        if quote not in source:
            failures.append({"id": example["id"], "reason": "quote_not_in_live_source"})
        if metadata["citation"]["page_start"] is None:
            failures.append({"id": example["id"], "reason": "missing_page"})

    return {
        "examples": len(examples),
        "verified": len(examples) - len({failure["id"] for failure in failures}),
        "failed": len({failure["id"] for failure in failures}),
        "failures": failures[:50],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
    temporary.replace(path)
