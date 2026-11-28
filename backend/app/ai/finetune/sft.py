"""Supervised fine-tuning records, validation and JSONL output."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from app.ai.finetune.claims import ClaimClassification
from app.ai.finetune.config import SAFETY_NOTE, SFT_SYSTEM_PROMPT
from app.ai.finetune.models import CleanChunk, LicenceDecision

_PII = re.compile(
    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|\+\d{1,3}[\s-]?\d{6,}|\b\d{10,}\b",
    re.IGNORECASE,
)


def build_sft_example(
    *,
    example_id: str,
    question: str,
    answer_quote: str,
    clean_chunk: CleanChunk,
    licence: LicenceDecision,
    classification: ClaimClassification,
    question_type: str,
    display_author: str | None = None,
) -> dict[str, Any]:
    chunk = clean_chunk.chunk
    book = clean_chunk.book
    section = clean_chunk.section
    page_start, page_end = clean_chunk.pages
    page_label = (
        f"p. {page_start}"
        if page_end in (None, page_start)
        else f"pp. {page_start}-{page_end}"
    )
    author = display_author or book.display_author
    answer = (
        f'"{answer_quote}"\n\n'
        f"Source: {author}, {book.title}, {page_label}."
    )
    metadata = {
        "example_id": example_id,
        "question_type": question_type,
        "answer_quote": answer_quote,
        "source": {
            "book_id": book.id,
            "book_title": book.title,
            "author": book.author,
            "category": book.category,
            "source_filename": book.source_filename,
            "book_content_hash": book.content_hash,
        },
        "citation": {
            "page_start": page_start,
            "page_end": page_end,
            "section_id": chunk.section_id,
            "section_heading": section.heading if section else chunk.metadata.get("section"),
            "section_path": list(section.path) if section else list(
                chunk.metadata.get("rubric_path") or []
            ),
            "chunk_index": chunk.chunk_index,
            "chunk_content_hash": chunk.content_hash,
            "source_char_start": chunk.metadata.get("source_char_start"),
            "source_char_end": chunk.metadata.get("source_char_end"),
        },
        "evidence": classification.to_dict(),
        "licence": {
            "status": licence.status,
            "basis": licence.basis,
            "legal_review": licence.legal_review,
        },
        "safety_note": SAFETY_NOTE,
    }
    return {
        "id": example_id,
        "messages": [
            {"role": "system", "content": SFT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
        "metadata": metadata,
    }


def validate_example(
    example: dict[str, Any],
    clean_chunk: CleanChunk,
    licence: LicenceDecision,
) -> list[str]:
    """Return a list of failed checks. An empty list means the example passed."""
    errors: list[str] = []
    messages = example.get("messages")
    if not isinstance(messages, list) or [m.get("role") for m in messages] != [
        "system",
        "user",
        "assistant",
    ]:
        return ["message_roles"]
    if not all(isinstance(m.get("content"), str) and m["content"].strip() for m in messages):
        errors.append("empty_message")

    metadata = example.get("metadata") or {}
    quote = metadata.get("answer_quote") or ""
    if not quote:
        errors.append("missing_quote")
    else:
        haystack = " ".join(clean_chunk.text.split())
        needle = " ".join(quote.split())
        if needle not in haystack:
            errors.append("quote_not_in_source")
        if needle not in " ".join(messages[2]["content"].split()):
            errors.append("quote_not_in_answer")

    if not licence.cleared or not licence.exportable:
        errors.append("licence_not_exportable")
    if metadata.get("source", {}).get("book_content_hash") != clean_chunk.book.content_hash:
        errors.append("book_hash_mismatch")
    if metadata.get("citation", {}).get("chunk_content_hash") != clean_chunk.chunk.content_hash:
        errors.append("chunk_hash_mismatch")
    if metadata.get("citation", {}).get("page_start") is None:
        errors.append("missing_page")
    if metadata.get("evidence", {}).get("evidence_class") != "historical_homeopathic_claim":
        errors.append("evidence_class")

    combined = "\n".join(m["content"] for m in messages)
    if _PII.search(combined):
        errors.append("personal_information")
    return errors


def verification_summary(results: list[list[str]]) -> dict[str, Any]:
    failures: dict[str, int] = {}
    for errors in results:
        for error in errors:
            failures[error] = failures.get(error, 0) + 1
    passed = sum(1 for errors in results if not errors)
    return {
        "examples": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "failure_reasons": dict(sorted(failures.items())),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Write JSONL atomically and return file size and checksum."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    digest = hashlib.sha256()
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, allow_nan=False)
            stream.write(line + "\n")
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return {
        "path": str(path),
        "records": len(records),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
