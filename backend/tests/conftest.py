"""Shared test doubles: deterministic mock embeddings and an in-memory
knowledge database that mirrors the persistence contract (including
ignore-duplicates upserts and NULL-embedding resume)."""

import hashlib
import random
import uuid

import pytest

from app.services import knowledge_db
from app.services.embeddings import EmbeddingResult

MOCK_DIMENSION = 1024


class MockEmbeddingProvider:
    """Deterministic 1024-dim embeddings (no network, no model)."""

    dimension = MOCK_DIMENSION

    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
        return [random.Random(seed + i).uniform(-1, 1) for i in range(8)] * (MOCK_DIMENSION // 8)

    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        self.document_calls.append(list(texts))
        tokens = sum(max(1, len(t) // 4) for t in texts)
        return EmbeddingResult(embeddings=[self._vector(t) for t in texts], total_tokens=tokens)

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)


class FakeKnowledgeDB:
    """In-memory stand-in for the Supabase-backed knowledge_db functions."""

    def __init__(self) -> None:
        self.books: dict[str, dict] = {}
        self.sections: list[dict] = []
        self.chunks: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.events: list[dict] = []
        self._sequence = 0
        self.flags: dict[str, dict] = {}

    def update_book_metadata(self, book_id: str, patch: dict) -> None:
        book = self.books[book_id]
        book["metadata"] = {**(book.get("metadata") or {}), **patch}

    def get_system_flag(self, key: str) -> dict | None:
        return self.flags.get(key)

    def set_system_flag(self, key: str, *, paused: bool, reason: str | None, by: str) -> None:
        self.flags[key] = {"key": key, "paused": paused, "reason": reason, "set_by": by}

    # -- books --------------------------------------------------------------

    def create_book(self, book: dict) -> dict:
        row = {**book, "id": str(uuid.uuid4()), "section_count": 0, "chunk_count": 0}
        self.books[row["id"]] = row
        return row

    def get_book(self, book_id: str, include_text: bool = False) -> dict | None:
        row = self.books.get(book_id)
        if row is None or include_text:
            return row
        return {k: v for k, v in row.items() if k != "raw_text"}

    def list_books(self) -> list[dict]:
        return [self.get_book(book_id) for book_id in self.books]

    def find_book_by_content_hash(self, content_hash: str) -> dict | None:
        for row in self.books.values():
            if row["content_hash"] == content_hash:
                return self.get_book(row["id"])
        return None

    def update_book_counts(self, book_id: str, *, section_count: int, chunk_count: int) -> None:
        self.books[book_id].update(section_count=section_count, chunk_count=chunk_count)

    # -- sections and chunks ------------------------------------------------

    def upsert_sections(self, sections: list[dict]) -> list[dict]:
        rows = []
        for section in sections:
            existing = next(
                (
                    r
                    for r in self.sections
                    if r["book_id"] == section["book_id"] and r["ordinal"] == section["ordinal"]
                ),
                None,
            )
            if existing is None:
                existing = {**section, "id": str(uuid.uuid4())}
                self.sections.append(existing)
            else:
                existing.update(section)
            rows.append(dict(existing))
        return rows

    def upsert_chunks(self, chunks: list[dict]) -> None:
        for chunk in chunks:
            key = (chunk["book_id"], chunk["chunk_index"])
            if any((c["book_id"], c["chunk_index"]) == key for c in self.chunks.values()):
                continue  # ignore-duplicates: resume never duplicates rows
            self.chunks[str(uuid.uuid4())] = {**chunk, "embedding": None}

    def chunks_needing_embeddings(self, book_id: str, limit: int = 200) -> list[dict]:
        pending = [
            {
                "id": cid,
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "token_count": c.get("token_count"),  # the real query selects it too
            }
            for cid, c in sorted(self.chunks.items(), key=lambda kv: kv[1]["chunk_index"])
            if c["book_id"] == book_id and c["embedding"] is None
        ]
        return pending[:limit]

    def apply_chunk_embeddings(self, items: list[dict]) -> int:
        for item in items:
            self.chunks[item["id"]]["embedding"] = item["embedding"]
            # Like the real SQL function: token_count is overwritten by the item's value.
            self.chunks[item["id"]]["token_count"] = item.get("token_count")
        return len(items)

    # -- jobs ---------------------------------------------------------------

    def create_ingestion_job(self, book_id: str, extra: dict | None = None) -> dict:
        # The real table has a partial unique index: one pending/running job per book.
        if any(j["book_id"] == book_id and j["status"] in ("pending", "running")
               for j in self.jobs.values()):
            raise knowledge_db.KnowledgeDBError(
                "duplicate key value violates unique constraint "
                '"ingestion_jobs_one_active_per_book"'
            )
        self._sequence += 1
        row = {
            "id": str(uuid.uuid4()),
            "book_id": book_id,
            "status": "pending",
            "stage": "queued",
            "total_chunks": 0,
            "processed_chunks": 0,
            "embedded_tokens": 0,
            "error": None,
            "pause_requested": False,
            "token_limit": None,
            "estimated_tokens": None,
            "stop_reason": None,
            "resumed_from": None,
            "heartbeat_at": None,
            "started_at": None,
            "finished_at": None,
            "created_at": f"2026-11-23T10:00:{self._sequence:02d}+00:00",
            "_order": self._sequence,
            **(extra or {}),
        }
        self.jobs[row["id"]] = row
        return dict(row)

    def list_ingestion_jobs(self, *, book_id=None, statuses=None, limit=10) -> list[dict]:
        rows = [
            dict(j) for j in self.jobs.values()
            if (book_id is None or j["book_id"] == book_id)
            and (not statuses or j["status"] in statuses)
        ]
        rows.sort(key=lambda j: j["_order"], reverse=True)
        return rows[:limit]

    def budget_tokens_used(self) -> int:
        return sum(int(j.get("embedded_tokens") or 0) for j in self.jobs.values())

    def add_ingestion_event(self, *, job_id, book_id, level, kind, message, details=None) -> None:
        self.events.append({
            "id": len(self.events) + 1, "job_id": job_id, "book_id": book_id, "level": level,
            "kind": kind, "message": message, "details": details or {},
            "created_at": "2026-11-23T10:00:00+00:00",
        })

    def list_ingestion_events(self, *, book_id=None, job_id=None, limit=50) -> list[dict]:
        rows = [e for e in self.events
                if (book_id is None or e["book_id"] == book_id)
                and (job_id is None or e["job_id"] == job_id)]
        return sorted(rows, key=lambda e: e["id"], reverse=True)[:limit]

    def book_stats(self) -> list[dict]:
        stats: dict[str, dict] = {}
        for chunk in self.chunks.values():
            row = stats.setdefault(chunk["book_id"], {
                "book_id": chunk["book_id"], "total_chunks": 0, "embedded_chunks": 0,
                "embedded_tokens": 0, "pending_tokens": 0})
            row["total_chunks"] += 1
            tokens = int(chunk.get("token_count") or 0)
            if chunk["embedding"] is None:
                row["pending_tokens"] += tokens
            else:
                row["embedded_chunks"] += 1
                row["embedded_tokens"] += tokens
        return list(stats.values())

    def list_chunks(self, book_id, *, offset=0, limit=20, query=None, embedded=None) -> list[dict]:
        rows = []
        for cid, c in sorted(self.chunks.items(), key=lambda kv: kv[1]["chunk_index"]):
            if c["book_id"] != book_id:
                continue
            has_vector = c["embedding"] is not None
            if embedded is not None and has_vector != embedded:
                continue
            if query and query.lower() not in c["content"].lower():
                continue
            section = next((s for s in self.sections if s.get("id") == c.get("section_id")), {})
            rows.append({
                "id": cid, "chunk_index": c["chunk_index"], "content": c["content"],
                "token_count": c.get("token_count"), "embedded": has_vector,
                "metadata": c.get("metadata") or {}, "section_heading": section.get("heading"),
                "section_path": section.get("path") or [],
            })
        total = len(rows)
        return [{**r, "total": total} for r in rows[offset:offset + limit]]

    def get_ingestion_job(self, job_id: str) -> dict | None:
        row = self.jobs.get(job_id)
        return dict(row) if row else None

    def update_ingestion_job(self, job_id: str, fields: dict) -> None:
        self.jobs[job_id].update(fields)


def install_fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeKnowledgeDB:
    """Point the knowledge_db module functions at an in-memory fake."""
    fake = FakeKnowledgeDB()
    for name in (
        "create_book",
        "get_book",
        "list_books",
        "find_book_by_content_hash",
        "update_book_counts",
        "upsert_sections",
        "upsert_chunks",
        "chunks_needing_embeddings",
        "apply_chunk_embeddings",
        "create_ingestion_job",
        "get_ingestion_job",
        "update_ingestion_job",
        "list_ingestion_jobs",
        "budget_tokens_used",
        "add_ingestion_event",
        "list_ingestion_events",
        "book_stats",
        "list_chunks",
        "get_system_flag",
        "update_book_metadata",
        "set_system_flag",
    ):
        # Production functions take a client first; bound fake methods do not.
        def forward(_client, *args, _name=name, **kwargs):
            return getattr(fake, _name)(*args, **kwargs)

        monkeypatch.setattr(knowledge_db, name, forward)
    return fake


@pytest.fixture(autouse=True)
def _no_database_for_the_provider_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real provider-stop flag; the file manifest still applies."""
    from app.ai.rag import guard

    guard.reset_cache()
    monkeypatch.setattr(guard, "_read_db_flag", lambda: None)
