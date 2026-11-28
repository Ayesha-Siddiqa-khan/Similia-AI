"""Duplicate and near-duplicate detection for training text.

Three passes run in order: exact hash, normalised hash (case and punctuation
insensitive), and shingle-based near-duplicate detection. The representative
of a group is the longest text, which is usually the least truncated copy.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.finetune.config import (
    NEAR_DUPLICATE_JACCARD,
    NEAR_DUPLICATE_MIN_TOKENS,
    SHINGLE_SIZE,
)

_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")
_BAND_MASK = 0xFFFF
_BAND_COUNT = 4


@dataclass(frozen=True)
class DuplicateGroup:
    representative: str
    members: tuple[str, ...]
    kind: str
    similarity: float | None = None


def normalise_text(text: str) -> str:
    lowered = text.lower()
    stripped = _NON_ALNUM.sub(" ", lowered)
    return _SPACES.sub(" ", stripped).strip()


def exact_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def normalised_hash(text: str) -> str:
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


def _shingles(text: str) -> frozenset[int] | None:
    tokens = normalise_text(text).split()
    if len(tokens) < NEAR_DUPLICATE_MIN_TOKENS:
        return None
    hashes = {
        int.from_bytes(
            hashlib.blake2b(
                " ".join(tokens[index : index + SHINGLE_SIZE]).encode("utf-8"),
                digest_size=8,
            ).digest(),
            "big",
        )
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    }
    return frozenset(hashes)


def _jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _choose_representative(members: list[tuple[str, str]]) -> str:
    # Longest text first (least truncated copy), then earliest id for a stable
    # and reproducible representative.
    return min(members, key=lambda item: (-len(item[1]), item[0]))[0]


def _group_by_key(
    items: list[tuple[str, str]],
    key_fn: Callable[[str], str],
    kind: str = "exact",
) -> list[DuplicateGroup]:
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in items:
        buckets[key_fn(item[1])].append(item)
    groups: list[DuplicateGroup] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        representative = _choose_representative(members)
        groups.append(
            DuplicateGroup(
                representative=representative,
                members=tuple(sorted(item[0] for item in members)),
                kind=kind,
            )
        )
    return groups


def _near_duplicate_groups(items: list[tuple[str, str]]) -> list[DuplicateGroup]:
    shingle_sets: dict[str, frozenset[int]] = {}
    buckets: dict[int, list[str]] = defaultdict(list)
    for item_id, text in items:
        shingles = _shingles(text)
        if shingles is None:
            continue
        shingle_sets[item_id] = shingles
        seen_bands: set[int] = set()
        for value in shingles:
            for band in range(_BAND_COUNT):
                token = (value >> (band * 16)) & _BAND_MASK
                if token in seen_bands:
                    continue
                seen_bands.add(token)
                buckets[token].append(item_id)

    candidates: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2 or len(members) > 40:
            # A very large bucket is a common phrase and not discriminative.
            continue
        for left_index in range(len(members)):
            for right_index in range(left_index + 1, len(members)):
                left, right = members[left_index], members[right_index]
                if left == right:
                    continue
                candidates.add((min(left, right), max(left, right)))

    parent: dict[str, str] = {item_id: item_id for item_id in shingle_sets}
    similarity: dict[tuple[str, str], float] = {}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left, right in sorted(candidates):
        score = _jaccard(shingle_sets[left], shingle_sets[right])
        if score >= NEAR_DUPLICATE_JACCARD:
            similarity[(left, right)] = score
            union(left, right)

    components: dict[str, list[str]] = defaultdict(list)
    for item_id in shingle_sets:
        components[find(item_id)].append(item_id)

    groups: list[DuplicateGroup] = []
    by_id = dict(items)
    for members in components.values():
        if len(members) < 2:
            continue
        representative = _choose_representative([(item_id, by_id[item_id]) for item_id in members])
        scores = [
            score
            for (left, right), score in similarity.items()
            if left in members and right in members
        ]
        groups.append(
            DuplicateGroup(
                representative=representative,
                members=tuple(sorted(members)),
                kind="near",
                similarity=round(max(scores), 4) if scores else None,
            )
        )
    return groups


def find_duplicates(
    items: list[tuple[str, str]],
) -> tuple[list[DuplicateGroup], dict[str, tuple[str, str]]]:
    """Return all duplicate groups and a map of duplicate id to (representative, kind)."""
    groups: list[DuplicateGroup] = []
    assigned: dict[str, tuple[str, str]] = {}

    for group in _group_by_key(items, exact_hash):
        groups.append(group)
        for member in group.members:
            if member != group.representative and member not in assigned:
                assigned[member] = (group.representative, "exact")

    # Later passes only see representatives, so a duplicate is never chained
    # to another duplicate and the representative always stays canonical.
    remaining = [item for item in items if item[0] not in assigned]
    for group in _group_by_key(remaining, normalised_hash, kind="normalised"):
        groups.append(group)
        for member in group.members:
            if member != group.representative and member not in assigned:
                assigned[member] = (group.representative, "normalised")

    remaining = [item for item in items if item[0] not in assigned]
    for group in _near_duplicate_groups(remaining):
        groups.append(group)
        for member in group.members:
            if member != group.representative and member not in assigned:
                assigned[member] = (group.representative, "near")

    return groups, assigned
