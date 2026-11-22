"""Bounded ingestion using existing Supabase tables plus a durable local vector outbox.

Vectors and usage are committed locally before any remote write. If a process
dies during a provider call, the reservation stays charged and automatic replay
stops: a lost response cannot prove that a request was not billed.
"""

import json
import math
import sqlite3
import statistics
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.ai.ingestion.local import REPORTS, batches, now, read_json, save_json
from app.services import knowledge_db as db


class Paused(RuntimeError):
    """Safe, resumable stop (budget, quota, ambiguous request or sample boundary)."""


def retry_delay(exc: Exception, attempt: int) -> float:
    headers = {k.lower(): v for k, v in getattr(exc, "headers", {}).items()}
    value = headers.get("retry-after")
    try:
        server = float(value)
    except (TypeError, ValueError):
        try:
            server = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            server = 0
    return max(2 ** (attempt + 1), server)


class SupabaseSink:
    """Reuse the schema/RPCs and admin client; never relax RLS or migrate tables."""

    def __init__(self, client: Any, output: Path = REPORTS) -> None:
        self.client = client
        self.output = output

    def preflight(self) -> None:
        for table in (
            "knowledge_books",
            "knowledge_sections",
            "knowledge_chunks",
            "ingestion_jobs",
        ):
            self.client.table(table).select("id").limit(1).execute()

    def prepare(self, plan: dict[str, Any]) -> tuple[str, str]:
        book = plan["book"]
        existing = db.find_book_by_content_hash(self.client, book["file_hash"])
        if existing and existing.get("metadata", {}).get("plan_hash") != plan["plan_hash"]:
            raise ValueError(
                "Existing book has a different ingestion plan; refusing to overwrite it"
            )
        if not existing:
            text = (self.output / book["source_directory"] / "original.txt").read_bytes().decode()
            existing = db.create_book(
                self.client,
                {
                    "id": str(uuid5(NAMESPACE_URL, "similia:" + book["file_hash"])),
                    "category": book["category"],
                    "title": book["title"],
                    "author": book["author"],
                    "source_filename": book["filename"],
                    "content_hash": book["file_hash"],
                    "raw_text": text,
                    "metadata": {
                        "plan_hash": plan["plan_hash"],
                        "parts": plan["parts"],
                        "source_bytes": book["text_bytes"],
                        "pdf_bytes": book["pdf_bytes"],
                        "pipeline_version": plan["pipeline_version"],
                    },
                },
            )
        book_id = existing["id"]
        section_rows = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"{book_id}:section:{s['ordinal']}")),
                "book_id": book_id,
                "ordinal": s["ordinal"],
                "heading": s["heading"],
                "section_type": s["kind"],
                "path": s["path"],
                "metadata": {
                    "source_char_start": s["start"],
                    "source_char_end": s["end"],
                    "identifier": s["identifier"],
                },
            }
            for s in plan["sections"]
        ]
        sections = db.upsert_sections(self.client, section_rows)
        section_ids = {s["ordinal"]: s["id"] for s in sections}
        rows = []
        for c in plan["chunks"]:
            c["id"] = str(uuid5(NAMESPACE_URL, f"{book_id}:chunk:{c['chunk_index']}"))
            c["book_id"] = book_id
            rows.append(
                {
                    k: c[k]
                    for k in (
                        "id",
                        "book_id",
                        "chunk_index",
                        "content",
                        "content_hash",
                        "token_count",
                    )
                }
                | {
                    "section_id": section_ids[c["section_ordinal"]],
                    "metadata": c["metadata"]
                    | {
                        "book_title": book["title"],
                        "category": book["category"],
                        "author": book["author"],
                        "ingestion_status": "planned",
                    },
                }
            )
        db.upsert_chunks(self.client, rows)
        db.update_book_counts(
            self.client, book_id, section_count=len(sections), chunk_count=len(rows)
        )
        active = (
            self.client.table("ingestion_jobs")
            .select("*")
            .eq("book_id", book_id)
            .in_("status", ["pending", "running"])
            .execute()
            .data
        )
        job = active[0] if active else db.create_ingestion_job(self.client, book_id)
        db.update_ingestion_job(
            self.client,
            job["id"],
            {
                "status": "running",
                "stage": "prepared",
                "started_at": now(),
                "total_chunks": len(rows),
                "error": None,
            },
        )
        persisted_job = db.get_ingestion_job(self.client, job["id"])
        if (
            not persisted_job
            or persisted_job.get("status") != "running"
            or (
                persisted_job.get("book_id") != book_id
                or persisted_job.get("total_chunks") != len(rows)
            )
        ):
            raise RuntimeError("Remote ingestion checkpoint write was not verified")
        return book_id, job["id"]

    def verified(self, chunks: list[dict[str, Any]]) -> set[str]:
        if not chunks:
            return set()
        expected = {c["id"]: c for c in chunks}
        rows = (
            self.client.table("knowledge_chunks")
            .select("id,content_hash,embedding")
            .in_("id", list(expected))
            .execute()
            .data
        )
        result = set()
        if {r["id"] for r in rows} != set(expected):
            raise RuntimeError(
                "Some planned chunks were not stored; refusing to spend embedding tokens"
            )
        for row in rows:
            if row["content_hash"] != expected[row["id"]]["content_hash"]:
                raise ValueError("Remote chunk content hash does not match the frozen plan")
            vector = row["embedding"]
            if vector is None:
                continue
            if isinstance(vector, str):
                vector = json.loads(vector)
            if len(vector) != 1024 or not all(math.isfinite(v) for v in vector):
                raise ValueError("Stored vector failed dimension/finite-value verification")
            result.add(row["id"])
        return result

    def commit(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        items = [
            {"id": c["id"], "embedding": v, "token_count": c["token_count"]}
            for c, v in zip(chunks, vectors, strict=True)
        ]
        updated = db.apply_chunk_embeddings(self.client, items)
        if updated != len(items) or self.verified(chunks) != {c["id"] for c in chunks}:
            raise RuntimeError("Embedding write could not be verified; cached vectors retained")

    def progress(self, job_id: str, values: dict[str, Any]) -> None:
        db.update_ingestion_job(self.client, job_id, values)


class Journal:
    """SQLite FULL-synchronous checkpoints: usage ledger, vector outbox, book state."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY, batch_id TEXT, reserved INTEGER NOT NULL,
                actual INTEGER, status TEXT NOT NULL, timestamp TEXT NOT NULL
            );
        """)

    def get(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value: Any) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO state VALUES (?,?)",
                (key, json.dumps(value, allow_nan=False)),
            )

    def usage(self, batch_prefix: str | None = None) -> dict[str, Any]:
        query = "SELECT reserved,actual,status FROM requests"
        parameters: tuple[str, ...] = ()
        if batch_prefix is not None:
            query += " WHERE batch_id LIKE ?"
            parameters = (batch_prefix + "%",)
        rows = self.connection.execute(query + " ORDER BY id", parameters).fetchall()
        return {
            "provider_reported_tokens": sum(a or 0 for _, a, _ in rows),
            "budget_charged_tokens": sum(a if a is not None else r for r, a, _ in rows),
            "successful_requests": sum(s == "success" for _, _, s in rows),
            "failed_requests": sum(s not in ("success", "inflight") for _, _, s in rows),
            "ambiguous_requests": sum(s == "inflight" for _, _, s in rows),
            "unknown_usage_reserved_tokens": sum(r for r, a, _ in rows if a is None),
            "account_remaining_free_quota": "unknown",
        }

    def reserve(self, batch_id: str, amount: int, limit: int) -> int:
        with self.connection:
            if self.usage()["budget_charged_tokens"] + amount > limit:
                raise Paused("Configured embedding budget reached; next batch remains pending")
            cursor = self.connection.execute(
                "INSERT INTO requests(batch_id,reserved,status,timestamp) VALUES (?,?,?,?)",
                (batch_id, amount, "inflight", now()),
            )
        return int(cursor.lastrowid)

    def finish_request(self, request_id: int, status: str, actual: int | None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE requests SET status=?,actual=? WHERE id=?", (status, actual, request_id)
            )

    def cache_success(self, request_id: int, batch_id: str, data: dict[str, Any]) -> None:
        # A single local transaction records both usage and recoverable embeddings.
        with self.connection:
            self.connection.execute(
                "UPDATE requests SET status='success',actual=? WHERE id=?",
                (data["total_tokens"], request_id),
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO state VALUES (?,?)",
                (batch_id, json.dumps(data, allow_nan=False)),
            )

    def cached_vectors(self, chunk_ids: set[str]) -> dict[str, list[float]]:
        result = {}
        for (value,) in self.connection.execute("SELECT value FROM state WHERE key LIKE 'batch:%'"):
            batch = json.loads(value)
            for key, vector in zip(batch["chunk_ids"], batch["vectors"], strict=True):
                if key in chunk_ids:
                    result[key] = vector
        return result


class ResumableRunner:
    def __init__(
        self,
        sink: Any,
        embedder: Any,
        output: Path = REPORTS,
        budget: int = 200_000,
        max_chunks: int = 16,
        max_tokens: int = 10_000,
        sleep: Callable[[float], None] = time.sleep,
        interval: float = 20,
    ) -> None:
        self.sink, self.embedder, self.output = sink, embedder, output
        self.budget, self.max_chunks, self.max_tokens = budget, max_chunks, max_tokens
        self.sleep, self.interval = sleep, interval
        self.journal = Journal(output / "checkpoint.sqlite3")

    def pace(self, amount: int) -> None:
        """Respect a rolling 60-second trial window, including failed attempts."""
        current = time.time()
        deadline = self.journal.get("next_request_at", 0)
        recent = [
            (datetime.fromisoformat(stamp).timestamp(), reserved)
            for stamp, reserved in self.journal.connection.execute(
                "SELECT timestamp,reserved FROM requests ORDER BY id"
            )
            if datetime.fromisoformat(stamp).timestamp() > current - 60
        ]
        total = sum(tokens for _, tokens in recent)
        while recent and (len(recent) >= 3 or total + amount > 10_000):
            stamp, tokens = recent.pop(0)
            deadline = max(deadline, stamp + 60.1)
            total -= tokens
        if deadline > current:
            self.sleep(deadline - current)

    def request(self, batch_id: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        from voyageai import error

        cached = self.journal.get(batch_id)
        if cached is not None:
            return cached
        amount = sum(c["token_count"] + 16 for c in chunks)
        for attempt in range(5):
            self.pace(amount)
            request_id = self.journal.reserve(batch_id, amount, self.budget)
            self.journal.put(
                "next_request_at", time.time() + max(self.interval, 60 * amount / 10_000)
            )
            try:
                result = self.embedder.embed_documents([c["content"] for c in chunks])
            except Exception as exc:
                status = getattr(exc, "http_status", None)
                definitive_rejection = status in (400, 401, 402, 403, 413, 429)
                self.journal.finish_request(
                    request_id, type(exc).__name__, 0 if definitive_rejection else None
                )
                if (status == 413 or (status == 429 and attempt >= 1)) and len(chunks) > 1:
                    midpoint = len(chunks) // 2
                    left = self.request(batch_id + ":a", chunks[:midpoint])
                    right = self.request(batch_id + ":b", chunks[midpoint:])
                    combined = {
                        "vectors": left["vectors"] + right["vectors"],
                        "chunk_ids": left["chunk_ids"] + right["chunk_ids"],
                        "total_tokens": left["total_tokens"] + right["total_tokens"],
                        "status": "embedded",
                        "timestamp": now(),
                    }
                    self.journal.put(batch_id, combined)
                    return combined
                retryable = isinstance(
                    exc,
                    (
                        error.RateLimitError,
                        error.APIConnectionError,
                        error.ServerError,
                        error.ServiceUnavailableError,
                        error.Timeout,
                    ),
                )
                quota = any(
                    w in str(exc).lower() for w in ("quota", "billing", "credit", "payment")
                )
                rate_limited = status == 429
                # A keyword in a 429 message is not proof the allowance is gone (the first live
                # run stopped on that guess). A rejected 429 is not billed, so retry a few times
                # after a real wait; only then stop. Other keyword matches (402...) stop at once.
                quota_stop = quota and (attempt >= 2 if rate_limited else True)
                if not retryable or quota_stop or attempt == 4:
                    from app.ai.ingestion.service import provider_error_details

                    details = provider_error_details(exc)
                    raise Paused(
                        f"Embedding request stopped: {type(exc).__name__}, HTTP {status}; "
                        f"retry-after {details['retry_after_seconds']}; "
                        f"provider said: {details['message']}"
                    ) from None
                delay = retry_delay(exc, attempt)
                if rate_limited:
                    delay = max(delay, 60.0 * (attempt + 1))
                self.journal.put(
                    "next_request_at",
                    max(self.journal.get("next_request_at", 0), time.time() + delay),
                )
                continue
            data = {
                "vectors": result.embeddings,
                "total_tokens": result.total_tokens,
                "status": "embedded",
                "timestamp": now(),
                "chunk_ids": [c["id"] for c in chunks],
            }
            self.journal.cache_success(request_id, batch_id, data)
            if len(result.embeddings) != len(chunks) or any(
                len(v) != 1024 or not all(math.isfinite(x) for x in v) for v in result.embeddings
            ):
                raise Paused("Provider vector shape invalid; response cached, no remote write")
            if result.total_tokens > amount:
                raise Paused(
                    "Provider usage exceeded reservation; reconcile budget before continuing"
                )
            return data
        raise Paused("Retry limit reached")

    def run_book(self, plan: dict[str, Any], sample_limit: int | None = None) -> None:
        book = plan["book"]
        key = "book:" + book["file_hash"]
        state = self.journal.get(key, {})
        if state and state["plan_hash"] != plan["plan_hash"]:
            raise Paused("Plan changed; refusing to reuse a checkpoint with different chunks")
        book_id, job_id = self.sink.prepare(plan)
        state = state | {
            "book_id": book_id,
            "job_id": job_id,
            "plan_hash": plan["plan_hash"],
            "completed_indices": state.get("completed_indices", []),
            "status": "running",
            "error": None,
            "timestamp": now(),
        }
        self.journal.put(key, state)
        try:
            if self.journal.usage()["ambiguous_requests"]:
                raise Paused(
                    "A request was interrupted before its result was cached; "
                    "manual reconciliation required"
                )
            committed_this_run = 0
            work = plan["chunks"]
            if sample_limit is not None and work:
                first_part = work[0]["metadata"]["processing_part"]
                work = [c for c in work if c["metadata"]["processing_part"] == first_part]
            if sample_limit is not None and len(work) > sample_limit:
                indices = sorted(
                    {round(i * (len(work) - 1) / (sample_limit - 1)) for i in range(sample_limit)}
                )
                work = [work[i] for i in indices]
            for batch in batches(work, self.max_chunks, self.max_tokens):
                part = batch[0]["metadata"]["processing_part"]
                batch_id = f"batch:{plan['plan_hash']}:{part}:" + ",".join(c["id"] for c in batch)
                cached = self.journal.get(batch_id)
                verified = self.sink.verified(batch)
                if verified != {c["id"] for c in batch}:
                    # A partly committed/changed batch is recovered chunk by chunk from the outbox.
                    if cached is None:
                        pending = [c for c in batch if c["id"] not in verified]
                        available = self.journal.cached_vectors({c["id"] for c in pending})
                        missing = [c for c in pending if c["id"] not in available]
                        if sample_limit is not None:
                            remaining = sample_limit - committed_this_run
                            if remaining < len(missing):
                                raise Paused("Sample limit reached; validated batches preserved")
                        if missing:
                            fresh = self.request(batch_id + ":missing", missing)
                            available.update(
                                dict(zip(fresh["chunk_ids"], fresh["vectors"], strict=True))
                            )
                        cached = {
                            "chunk_ids": [c["id"] for c in pending],
                            "vectors": [available[c["id"]] for c in pending],
                            "total_tokens": 0,
                            "status": "embedded",
                            "timestamp": now(),
                        }
                        self.journal.put(batch_id, cached)
                    by_id = dict(zip(cached["chunk_ids"], cached["vectors"], strict=True))
                    pending = [c for c in batch if c["id"] not in verified]
                    if any(c["id"] not in by_id for c in pending):
                        raise Paused("Cached vectors do not cover the pending batch")
                    self.sink.commit(pending, [by_id[c["id"]] for c in pending])
                    committed_this_run += len(pending)
                state["completed_indices"] = sorted(
                    set(state["completed_indices"]) | {c["chunk_index"] for c in batch}
                )
                state.update(
                    {
                        "last_batch_id": batch_id,
                        "last_part": part,
                        "last_page": batch[-1]["metadata"]["page_end"],
                        "last_section": batch[-1]["metadata"]["section"],
                        "last_stored_chunk": batch[-1]["id"],
                        "timestamp": now(),
                    }
                )
                self.journal.put(key, state)
                part_key = f"part:{plan['plan_hash']}:{part}"
                part_state = self.journal.get(part_key, {"completed_batch_ids": []})
                part_state.update(
                    {
                        "book_id": book_id,
                        "file_hash": book["file_hash"],
                        "part": part,
                        "last_completed_page": state["last_page"],
                        "last_completed_section": state["last_section"],
                        "last_stored_chunk": state["last_stored_chunk"],
                        "completed_batch_ids": sorted(
                            set(part_state["completed_batch_ids"]) | {batch_id}
                        ),
                        "timestamp": now(),
                    }
                )
                self.journal.put(part_key, part_state)
                if cached:
                    self.journal.put(batch_id, cached | {"status": "stored"})
                self.sink.progress(
                    job_id,
                    {
                        "stage": f"part_{part}",
                        "processed_chunks": len(state["completed_indices"]),
                        "embedded_tokens": self.book_tokens(plan),
                    },
                )
                self.report([plan])
            if sample_limit is not None:
                self.journal.put("sample:" + plan["plan_hash"], True)
            if len(state["completed_indices"]) != len(plan["chunks"]):
                raise Paused("Representative sample stored and verified; full run remains pending")
            state.update({"status": "completed", "timestamp": now()})
            self.journal.put(key, state)
            self.sink.progress(
                job_id,
                {"status": "completed", "stage": "completed", "finished_at": now(), "error": None},
            )
        except BaseException as exc:
            state.update(
                {
                    "status": "paused"
                    if isinstance(exc, (Paused, KeyboardInterrupt))
                    else "failed",
                    "error": type(exc).__name__
                    + (": " + str(exc) if isinstance(exc, Paused) else ""),
                    "timestamp": now(),
                }
            )
            self.journal.put(key, state)
            try:
                self.sink.progress(
                    job_id,
                    {
                        "status": "failed",
                        "stage": state["status"],
                        "error": state["error"],
                        "finished_at": now(),
                    },
                )
            except Exception:
                pass  # Local checkpoint is authoritative while Supabase is unavailable.
            raise
        finally:
            self.report([plan])

    def book_tokens(self, plan: dict[str, Any]) -> int:
        row = self.journal.connection.execute(
            "SELECT COALESCE(SUM(actual),0) FROM requests WHERE batch_id LIKE ?",
            (f"batch:{plan['plan_hash']}:%",),
        ).fetchone()
        return int(row[0])

    def report(self, plans: list[dict[str, Any]], status: str | None = None) -> None:
        # Preserve per-book reports when a later book emits its next batch update.
        old_path = self.output / "ingestion_progress.json"
        previous = read_json(old_path).get("books", []) if old_path.exists() else []
        records = {b["file_hash"]: b for b in previous}
        for plan in plans:
            book = plan["book"]
            state = self.journal.get("book:" + book["file_hash"], {})
            completed = set(state.get("completed_indices", []))
            book_usage = self.journal.usage(f"batch:{plan['plan_hash']}:")
            sizes = [c["token_count"] for c in plan["chunks"]]
            done = [c for c in plan["chunks"] if c["chunk_index"] in completed]
            ranges = sorted(
                (c["metadata"]["source_byte_start"], c["metadata"]["source_byte_end"]) for c in done
            )
            token_ranges = sorted(
                (c["metadata"]["source_token_start"], c["metadata"]["source_token_end"])
                for c in done
            )

            def union_size(intervals: list[tuple[int, int]]) -> int:
                total = end = 0
                for a, b in intervals:
                    total += max(0, b - max(a, end))
                    end = max(end, b)
                return total

            record = {
                **book,
                "status": state.get("status", status or "locally_prepared"),
                "generated_chunks": len(plan["chunks"]),
                "stored_vectors": len(completed),
                "remaining_chunks": len(plan["chunks"]) - len(completed),
                "processed_source_text_bytes": union_size(ranges),
                "unique_source_tokens_processed": union_size(token_ranges),
                "provider_reported_embedding_tokens": self.book_tokens(plan),
                "successful_api_requests": book_usage["successful_requests"],
                "failed_api_requests": book_usage["failed_requests"],
                "minimum_chunk_tokens": min(sizes, default=0),
                "maximum_chunk_tokens": max(sizes, default=0),
                "average_chunk_tokens": statistics.mean(sizes) if sizes else 0,
                "median_chunk_tokens": statistics.median(sizes) if sizes else 0,
                "completion_percent": 100 * len(completed) / max(1, len(plan["chunks"])),
                "current_checkpoint": {k: v for k, v in state.items() if k != "completed_indices"},
                "pending_chunk_indices": [
                    c["chunk_index"] for c in plan["chunks"] if c["chunk_index"] not in completed
                ],
                "parts": [
                    {
                        **p,
                        "stored_chunks": sum(
                            p["chunk_start"] <= i < p["chunk_end"] for i in completed
                        ),
                        "checkpoint": self.journal.get(f"part:{plan['plan_hash']}:{p['part']}", {}),
                        "usage": self.journal.usage(f"batch:{plan['plan_hash']}:{p['part']}:"),
                    }
                    for p in plan["parts"]
                ],
            }
            records[book["file_hash"]] = record
            usage = self.journal.usage()
            print(
                f"\nBook: {book['filename']}\n"
                f"Part: {state.get('last_part', 1)} / {len(plan['parts'])}; "
                f"last stored page: {state.get('last_page', 0)} / {book['total_pages']}\n"
                f"Original PDF: {book['pdf_bytes']:,} bytes; "
                f"extracted text: {book['text_bytes']:,} bytes\n"
                f"Processed source: {record['processed_source_text_bytes']:,} bytes; "
                f"unique source tokens: {record['unique_source_tokens_processed']:,}\n"
                f"Vectors committed: {record['stored_vectors']} / {len(plan['chunks'])}; "
                f"remaining: {record['remaining_chunks']}\n"
                f"Provider-reported tokens (book): {self.book_tokens(plan):,}; "
                f"run charged/reserved: {usage['budget_charged_tokens']:,}/{self.budget:,}\n"
                f"Run requests: {usage['successful_requests']} successful, "
                f"{usage['failed_requests']} failed\n"
                f"Completion: {record['completion_percent']:.1f}%; status: {record['status']}\n"
                f"Checkpoint: {state.get('last_stored_chunk', 'none')}",
                flush=True,
            )
        usage = self.journal.usage() | {
            "timestamp": now(),
            "max_run_embedding_tokens": self.budget,
            "embedding_model": "voyage-4-lite",
            "embedding_dimensions": 1024,
            "provider_model_revision": "not exposed by provider",
            "voyage_sdk_version": version("voyageai"),
            "langchain_voyageai_version": version("langchain-voyageai"),
            "books": [
                {
                    "file_hash": b["file_hash"],
                    "parts": b["parts"],
                    "provider_reported_tokens": b["provider_reported_embedding_tokens"],
                }
                for b in records.values()
            ],
        }
        save_json(self.output / "embedding_usage.json", usage)
        progress = {
            "timestamp": now(),
            "status": status or "see individual books",
            "books": list(records.values()),
            "usage": usage,
        }
        save_json(old_path, progress)
        lines = [
            "# Similia AI ingestion report",
            "",
            f"Updated: {now()}",
            "",
            f"Budget: {usage['budget_charged_tokens']:,} / {self.budget:,} tokens.",
            f"Provider-reported tokens: {usage['provider_reported_tokens']:,}.",
            "Remaining account-wide free quota: unknown.",
            "",
            "| Book | Status | Vectors | Completion |",
            "|---|---|---:|---:|",
        ]
        for b in records.values():
            lines.append(
                f"| {b['filename']} | {b['status']} | "
                f"{b['stored_vectors']}/{b['generated_chunks']} | {b['completion_percent']:.1f}% |"
            )
        for b in records.values():
            lines += [
                "",
                f"## {b['filename']}",
                "",
                f"Source SHA-256: `{b['file_hash']}`.",
                f"PDF: {b['pdf_bytes']:,} bytes; extracted text: {b['text_bytes']:,} bytes; "
                f"source tokens: {b['original_tokens']:,}.",
                f"Processed source: {b['processed_source_text_bytes']:,} unique bytes / "
                f"{b['unique_source_tokens_processed']:,} unique tokens.",
                f"Chunk tokens (min / max / mean / median): "
                f"{b.get('minimum_chunk_tokens', 0)} / {b.get('maximum_chunk_tokens', 0)} / "
                f"{b.get('average_chunk_tokens', 0):.1f} / {b.get('median_chunk_tokens', 0):.1f}.",
                f"Provider-reported tokens: {b['provider_reported_embedding_tokens']:,}; "
                f"successful / failed requests: {b.get('successful_api_requests', 0)} / "
                f"{b.get('failed_api_requests', 0)}.",
                f"Checkpoint: `{b['current_checkpoint'].get('last_stored_chunk', 'none')}`.",
            ]
        lines += [
            "",
            "Largest PDF excluded from embeddings.",
            "Image-only pages were visually checked as blank/cover pages; no OCR was added.",
            "The Organon source omits marker 227; its text and the boundary warning are retained.",
            "Retrieval of historical homeopathic text is not evidence of clinical efficacy.",
            "Coding-agent context/token usage is unavailable from this runtime.",
        ]
        (self.output / "ingestion_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
