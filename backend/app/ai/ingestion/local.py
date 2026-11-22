"""Local PDF inventory, immutable extraction artifacts, chunk plans and QA reports."""

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf

from app.ai.ingestion.adaptive import VERSION, TokenCounter, make_chunks, processing_parts

ROOT = Path(__file__).resolve().parents[4]
REPORTS = ROOT / "reports" / "ingestion"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: Any) -> None:
    """Flush before atomic replace; a torn write cannot replace the last checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_layout_hints(path: Path, extracted: dict[str, Any], output: Path) -> None:
    """Analyze new PDFs without changing the structure of an already-embedded book."""
    if extracted.get("layout_analysis"):
        return
    checkpoint = output / "checkpoint.sqlite3"
    frozen = False
    if checkpoint.exists():
        connection = sqlite3.connect(checkpoint)
        try:
            frozen = (
                connection.execute(
                    "SELECT 1 FROM state WHERE key=?", ("book:" + extracted["source_hash"],)
                ).fetchone()
                is not None
            )
        finally:
            connection.close()
    if frozen:
        extracted["layout_analysis"] = "existing_plan_frozen"
        return
    name_pattern = re.compile(r"[A-Z][a-z]+(?:[- ][a-z]+){0,3}")
    with pymupdf.open(path) as document:
        for page, stored in zip(document, extracted["pages"], strict=True):
            blocks = page.get_text(
                "dict", flags=(pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
            )["blocks"]
            spans = [
                span
                for block in blocks
                if block["type"] == 0
                for line in block["lines"]
                for span in line["spans"]
            ]
            sizes: Counter[float] = Counter()
            for span in spans:
                sizes[round(span["size"], 1)] += len(span["text"])
            body_size = sizes.most_common(1)[0][0] if sizes else 12
            hints = []
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    title = "".join(span["text"] for span in line["spans"]).strip()
                    if not name_pattern.fullmatch(title) or not line["spans"]:
                        continue
                    if max(span["size"] for span in line["spans"]) < max(20, body_size * 1.7):
                        continue
                    match = re.search(
                        r"(?m)^[ \t]*"
                        + r"[ \t]+".join(re.escape(word) for word in title.split())
                        + r"[ \t]*$",
                        stored["text"],
                    )
                    if match:
                        # splitlines offsets include the indentation but not a preceding blank line.
                        hints.append(
                            {"title": title, "char_start": stored["char_start"] + match.start()}
                        )
            stored["remedy_heading_hints"] = hints
    extracted["layout_analysis"] = "large_font_remedy_headings_v1"


def inventory(
    counter: TokenCounter,
    folder: Path,
    output: Path = REPORTS,
    include_added: bool = False,
) -> dict[str, Any]:
    books = []
    paths = sorted(folder.glob("*.pdf"))
    if not paths:
        raise ValueError("No PDFs found")
    previous_path = output / "pdf_inventory.json"
    previous = read_json(previous_path) if previous_path.exists() else {}
    initial_hashes = previous.get(
        "initial_document_hashes", [b["file_hash"] for b in previous.get("books", [])]
    )
    excluded = previous.get(
        "excluded_hashes",
        [
            b["file_hash"]
            for b in previous.get("books", [])
            if b["file_hash"] not in previous.get("selected_hashes", [])
        ],
    )
    for path in paths:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        directory = output / "sources" / digest
        cache = directory / "extraction.json"
        if cache.exists():
            extracted = read_json(cache)
        else:
            pages = []
            with pymupdf.open(path) as doc:
                if doc.needs_pass:
                    raise ValueError(f"Password protected PDF: {path.name}")
                author = doc.metadata.get("author") or None
                toc = doc.get_toc()
                char_offset = 0
                for i, page in enumerate(doc):
                    text = page.get_text("text", sort=True)
                    pages.append(
                        {
                            "page": i + 1,
                            "text": text,
                            "char_start": char_offset,
                            "image_count": len(page.get_images()),
                            "tokens": counter.count(text),
                            "replacement_characters": text.count("\ufffd"),
                        }
                    )
                    char_offset += len(text) + 1  # form-feed page separator
                    if (i + 1) % 100 == 0:
                        print(f"Extracting {path.name}: {i + 1}/{len(doc)} pages", flush=True)
            extracted = {
                "author": author,
                "toc": toc,
                "pages": pages,
                "source_hash": digest,
                "timestamp": now(),
            }
            save_json(cache, extracted)
        pages = extracted["pages"]
        text = "\f".join(p["text"] for p in pages)
        raw = directory / "original.txt"
        if not raw.exists():
            raw.write_bytes(text.encode("utf-8"))
        lower = path.stem.lower()
        category = (
            "organon"
            if "organon" in lower
            else "repertory"
            if "repertory" in lower
            else "materia_medica"
            if "materia" in lower
            else "general"
        )
        if category == "materia_medica":
            add_layout_hints(path, extracted, output)
            save_json(cache, extracted)
        tokens = counter.count(text)
        nontext = [p["page"] for p in pages if not p["text"].strip()]
        image_only = [p["page"] for p in pages if not p["text"].strip() and p["image_count"]]
        suspicious = [
            p["page"]
            for p in pages
            if p["text"].strip()
            and (
                p["replacement_characters"] / max(1, len(p["text"])) > 0.005
                or (
                    any(c.isalpha() for c in p["text"])
                    and sum(c.isalpha() for c in p["text"])
                    / max(1, sum(not c.isspace() for c in p["text"]))
                    < 0.25
                )
            )
        ]
        books.append(
            {
                "filename": path.name,
                "title": path.stem.replace("_", " "),
                "author": extracted["author"],
                "file_hash": digest,
                "pdf_bytes": path.stat().st_size,
                "pdf_mb": path.stat().st_size / 1_000_000,
                "total_pages": len(pages),
                "extractable_pages": len(pages) - len(nontext),
                "image_only_pages": image_only,
                "empty_or_unreadable_pages": nontext,
                "suspect_text_pages": suspicious,
                "symbol_only_pages": [
                    p["page"]
                    for p in pages
                    if p["text"].strip() and not any(c.isalnum() for c in p["text"])
                ],
                "extracted_characters": len(text),
                "text_bytes": len(text.encode("utf-8")),
                "original_tokens": tokens,
                "category": category,
                "estimated_chunks": math.ceil(tokens / (120 if category == "repertory" else 450)),
                "estimated_embedding_tokens": math.ceil(
                    tokens * (1 if category in ("organon", "repertory") else 450 / 390)
                ),
                "valid": bool(tokens)
                and not suspicious
                and len(nontext) / max(1, len(pages)) <= 0.1,
                "needs_ocr_review": len(nontext) / max(1, len(pages)) > 0.1,
                "source_directory": str(directory.relative_to(output)),
                "timestamp": now(),
                "tokenizer_hash": counter.hash,
            }
        )
        print(f"Inventoried {path.name}: {tokens:,} tokens", flush=True)
    books.sort(key=lambda b: b["original_tokens"])
    selected = previous.get("selected_hashes") or [b["file_hash"] for b in books if b["valid"]][:2]
    # Never silently substitute a different book when one of the two smallest is suspect.
    smallest = books[:2]
    if not previous and any(not b["valid"] for b in smallest):
        selected = []
    if include_added:
        selected = [b["file_hash"] for b in books if b["valid"] and b["file_hash"] not in excluded]
    if not initial_hashes:
        initial_hashes = [b["file_hash"] for b in books]
        excluded = [b["file_hash"] for b in books if b["file_hash"] not in selected]
    result = {
        "timestamp": now(),
        "books": books,
        "selected_hashes": selected,
        "initial_document_hashes": initial_hashes,
        "excluded_hashes": excluded,
        "token_counter": "official voyage-4-lite tokenizer; provider usage reconciled separately",
        "account_remaining_free_quota": "unknown",
    }
    save_json(output / "pdf_inventory.json", result)
    return result


def prepare(
    counter: TokenCounter,
    inv: dict[str, Any],
    output: Path = REPORTS,
    threshold: int = 100_000,
    max_budget: int = 200_000,
) -> list[dict[str, Any]]:
    plans = []
    for book in inv["books"]:
        if book["file_hash"] not in inv["selected_hashes"]:
            continue
        directory = output / book["source_directory"]
        extracted = read_json(directory / "extraction.json")
        text = (directory / "original.txt").read_bytes().decode("utf-8")
        sections, chunks = make_chunks(
            text,
            extracted["pages"],
            book["category"],
            counter,
            book["file_hash"],
            body_start=next(
                (
                    extracted["pages"][p - 1]["char_start"]
                    for _, heading, p in extracted["toc"]
                    if "MATERIA MEDICA" in heading.upper()
                    and p > 10
                    and p <= len(extracted["pages"])
                ),
                0,
            ),
        )
        parts = processing_parts(chunks, book["text_bytes"], book["original_tokens"], threshold)
        # The plan hash prevents a resumed job accepting changed chunking/tokenizers.
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "version": VERSION,
                    "tokenizer": counter.hash,
                    "parts": parts,
                    "chunks": [(c["content_hash"], c["metadata"]) for c in chunks],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        plan = {
            "book": book,
            "sections": sections,
            "chunks": chunks,
            "parts": parts,
            "plan_hash": fingerprint,
            "pipeline_version": VERSION,
            "timestamp": now(),
        }
        save_json(directory / "plan.json", plan)
        plans.append(plan)
    reports = []
    examples = []
    for plan in plans:
        counts = [c["token_count"] for c in plan["chunks"]]
        indices = sorted({round(i * (len(counts) - 1) / 9) for i in range(10)}) if counts else []
        sample = [plan["chunks"][i] for i in indices]
        for c in sample:
            meta = c["metadata"]
            examples.append(
                {
                    "book_hash": plan["book"]["file_hash"],
                    "chunk_index": c["chunk_index"],
                    "source_pages": [meta["page_start"], meta["page_end"]],
                    "query": "Find the passage concerning " + meta["section"],
                    "expected_content_hash": c["content_hash"],
                    "source_quote": c["content"].split("\n\n", 1)[-1][:180],
                }
            )
        save_json(output / plan["book"]["source_directory"] / "qa_sample.json", sample)
        reports.append(
            {
                "filename": plan["book"]["filename"],
                "file_hash": plan["book"]["file_hash"],
                "chunks": len(counts),
                "minimum_tokens": min(counts, default=0),
                "maximum_tokens": max(counts, default=0),
                "average_tokens": statistics.mean(counts) if counts else 0,
                "median_tokens": statistics.median(counts) if counts else 0,
                "embedding_input_tokens": sum(counts),
                "budget_reserved_estimate": sum(counts) + 16 * len(counts),
                "estimated_requests": len(batches(plan["chunks"])),
                "sections": len(plan["sections"]),
                "parts": plan["parts"],
                "aphorisms": [s["identifier"] for s in plan["sections"] if s["kind"] == "aphorism"],
                "missing_aphorism_markers": (
                    sorted(
                        set(range(1, 292))
                        - {
                            int(s["identifier"])
                            for s in plan["sections"]
                            if s["kind"] == "aphorism"
                        }
                    )
                    if plan["book"]["category"] == "organon"
                    else []
                ),
                "qa_sample_chunks": len(sample),
                "source_coverage_validated": True,
                "excluded_watermark_ranges": [
                    {"start": s["start"], "end": s["end"], "reason": s["heading"]}
                    for s in plan["sections"]
                    if s["kind"] == "artifact"
                ],
            }
        )
    total = sum(r["budget_reserved_estimate"] for r in reports)
    save_json(
        output / "chunking_report.json",
        {
            "timestamp": now(),
            "books": reports,
            "estimated_embedding_tokens": total,
            "max_run_embedding_tokens": max_budget,
            "fits_budget": total <= max_budget,
            "excluded_hashes": [
                b["file_hash"] for b in inv["books"] if b["file_hash"] not in inv["selected_hashes"]
            ],
        },
    )
    save_json(
        output / "retrieval_cases.json",
        {
            "timestamp": now(),
            "status": "prepared; live retrieval not yet evaluated",
            "clinical_efficacy": (
                "Retrieval of historical material is not evidence of clinical efficacy."
            ),
            "cases": examples,
        },
    )
    return plans


def batches(
    chunks: list[dict[str, Any]],
    max_chunks: int = 16,
    max_tokens: int = 10_000,
) -> list[list[dict[str, Any]]]:
    if max_chunks < 1 or max_tokens < 1:
        raise ValueError("Batch limits must be positive")
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for chunk in chunks:
        # Include a conservative allowance for Voyage's document input prompt.
        count = chunk["token_count"] + 16
        if count > max_tokens:
            raise ValueError("One chunk exceeds batch token limit")
        if current and (
            len(current) >= max_chunks
            or size + count > max_tokens
            or current[0]["metadata"]["processing_part"] != chunk["metadata"]["processing_part"]
        ):
            result.append(current)
            current, size = [], 0
        current.append(chunk)
        size += count
    if current:
        result.append(current)
    return result
