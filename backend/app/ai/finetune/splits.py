"""Deterministic book-level train/validation/test splits.

Books are never split at chunk level: chunk overlap and near-duplicate editions
would leak validation text into training. Assignment is reproducible from the
content hash and a fixed salt, and categories are interleaved so a small
corpus still produces a category spread.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from app.ai.finetune.config import (
    SPLIT_SALT,
    TEST_FRACTION,
    TRAIN_FRACTION,
    VALIDATION_FRACTION,
)
from app.ai.finetune.models import BookRecord, SplitAssignment


def _sort_key(book: BookRecord) -> str:
    return hashlib.sha256(f"{SPLIT_SALT}:{book.content_hash}".encode("utf-8")).hexdigest()


def _interleaved_order(books: list[BookRecord]) -> list[BookRecord]:
    by_category: dict[str, list[BookRecord]] = defaultdict(list)
    for book in books:
        by_category[book.category].append(book)
    for category_books in by_category.values():
        category_books.sort(key=_sort_key)
    ordered: list[BookRecord] = []
    depth = 0
    while True:
        added = False
        for category in sorted(by_category):
            category_books = by_category[category]
            if depth < len(category_books):
                ordered.append(category_books[depth])
                added = True
        if not added:
            return ordered
        depth += 1


def assign_splits(books: list[BookRecord]) -> list[SplitAssignment]:
    """Assign every book to exactly one split. Deterministic for a given input."""
    ordered = _interleaved_order(books)
    total = len(ordered)
    if total == 0:
        return []
    if total < 3:
        test_count = 0
        validation_count = 0
    else:
        test_count = max(1, round(total * TEST_FRACTION))
        validation_count = max(1, round(total * VALIDATION_FRACTION))
        # Always leave at least one training book.
        while test_count + validation_count >= total:
            if test_count >= validation_count and test_count > 1:
                test_count -= 1
            elif validation_count > 1:
                validation_count -= 1
            else:
                break

    assignments: list[SplitAssignment] = []
    for index, book in enumerate(ordered):
        if index < test_count:
            split, reason = "test", "first block after category-interleaved hash ordering"
        elif index < test_count + validation_count:
            split, reason = "validation", "second block after category-interleaved hash ordering"
        else:
            split, reason = "train", "remaining books"
        assignments.append(
            SplitAssignment(
                book_id=book.id,
                content_hash=book.content_hash,
                title=book.title,
                category=book.category,
                split=split,
                reason=reason,
            )
        )
    return assignments


def split_manifest(assignments: list[SplitAssignment]) -> dict:
    counts = {"train": 0, "validation": 0, "test": 0}
    for assignment in assignments:
        counts[assignment.split] += 1
    return {
        "strategy": "book_level_category_interleaved_hash",
        "salt": SPLIT_SALT,
        "fractions": {
            "train": TRAIN_FRACTION,
            "validation": VALIDATION_FRACTION,
            "test": TEST_FRACTION,
        },
        "counts": counts,
        "assignments": [assignment.to_dict() for assignment in assignments],
    }
