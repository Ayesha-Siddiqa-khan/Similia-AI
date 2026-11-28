"""Licence gate for training data.

The gate is deliberately conservative: a book is exportable only when the
registry contains an explicit, reviewed decision for its content hash. Any
missing or unrecognised book is blocked.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.ai.finetune.config import LICENCE_REGISTRY_PATH, POLICY_VERSION
from app.ai.finetune.models import BookRecord, LicenceDecision

VALID_STATUSES = frozenset(
    {
        "cleared_public_domain",
        "blocked_copyright",
        "blocked_unverified",
        "suppressed_duplicate",
    }
)


class LicenceRegistryError(RuntimeError):
    """The licence registry is missing, malformed or internally inconsistent."""


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, Any]:
    if not LICENCE_REGISTRY_PATH.exists():
        raise LicenceRegistryError(f"Licence registry not found: {LICENCE_REGISTRY_PATH}")
    try:
        payload = json.loads(LICENCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LicenceRegistryError(f"Licence registry is not valid JSON: {exc}") from exc
    if payload.get("version") != POLICY_VERSION:
        raise LicenceRegistryError(
            f"Licence registry version {payload.get('version')!r} "
            f"does not match policy {POLICY_VERSION!r}"
        )
    books = payload.get("books")
    if not isinstance(books, dict):
        raise LicenceRegistryError("Licence registry has no 'books' object")
    for content_hash, entry in books.items():
        if not isinstance(entry, dict):
            raise LicenceRegistryError(f"Registry entry {content_hash} is not an object")
        status = entry.get("status")
        if status not in VALID_STATUSES:
            raise LicenceRegistryError(
                f"Registry entry {content_hash} has unknown status {status!r}"
            )
        if status == "cleared_public_domain" and not entry.get("exportable", False):
            # Allowed: cleared but excluded for quality. Recorded explicitly.
            continue
    return payload


def decision_for(content_hash: str) -> LicenceDecision:
    """Return the registry decision, or a blocking default when absent."""
    registry = _load_registry()
    entry = registry["books"].get(content_hash)
    if entry is None:
        return LicenceDecision(
            status="blocked_unverified",
            basis="No licence decision exists for this content hash.",
            evidence=(),
            author_death_year=None,
            legal_review="required",
            exportable=False,
            display_author=None,
            notes="Add an explicit registry entry only after verifying the edition.",
        )
    return LicenceDecision(
        status=entry["status"],
        basis=entry.get("basis", ""),
        evidence=tuple(entry.get("evidence") or ()),
        author_death_year=entry.get("author_death_year"),
        legal_review=entry.get("legal_review", "required"),
        exportable=bool(entry.get("exportable", False)),
        display_author=entry.get("display_author"),
        notes=entry.get("notes", ""),
    )


def is_exportable(book: BookRecord) -> bool:
    decision = decision_for(book.content_hash)
    return decision.cleared and decision.exportable


def partition_books(
    books: list[BookRecord],
) -> tuple[list[BookRecord], list[BookRecord], list[BookRecord], list[BookRecord]]:
    """Split books into cleared, blocked, suppressed and cleared-but-excluded.

    Returns ``(exportable, blocked, suppressed, quality_excluded)``.
    """
    exportable: list[BookRecord] = []
    blocked: list[BookRecord] = []
    suppressed: list[BookRecord] = []
    quality_excluded: list[BookRecord] = []
    for book in books:
        decision = decision_for(book.content_hash)
        if decision.status == "suppressed_duplicate":
            suppressed.append(book)
        elif decision.cleared and decision.exportable:
            exportable.append(book)
        elif decision.cleared:
            quality_excluded.append(book)
        else:
            blocked.append(book)
    return exportable, blocked, suppressed, quality_excluded


def registry_summary() -> dict[str, int]:
    registry = _load_registry()
    counts: dict[str, int] = {}
    for entry in registry["books"].values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return counts
