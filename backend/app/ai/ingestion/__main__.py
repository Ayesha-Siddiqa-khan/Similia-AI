"""Run from backend: uv run --offline --no-sync python -m app.ai.ingestion [--live]."""

import argparse
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

from app.ai.ingestion.adaptive import TokenCounter
from app.ai.ingestion.local import REPORTS, ROOT, inventory, prepare, read_json
from app.ai.ingestion.resumable import Paused, ResumableRunner, SupabaseSink
from app.core.config import get_settings
from app.services.embeddings import get_embedding_provider
from app.services.supabase import get_supabase_admin_client


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    """OS lock releases on process death; never steal an expired timestamp lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            import msvcrt
        except ImportError:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        else:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Recheck PDF files locally")
    parser.add_argument(
        "--include-added-books",
        action="store_true",
        help="Inventory and queue added PDFs; preserve originally excluded books",
    )
    parser.add_argument(
        "--live", action="store_true", help="Embed and store the two selected books"
    )
    parser.add_argument("--sample", action="store_true", help="Only store 16 representative chunks")
    parser.add_argument(
        "--max-run-embedding-tokens", type=int, default=get_settings().max_run_embedding_tokens
    )
    parser.add_argument("--part-threshold", type=int, default=100_000)
    parser.add_argument("--batch-chunks", type=int, default=16)
    parser.add_argument("--batch-tokens", type=int, default=10_000)
    args = parser.parse_args()
    if (
        min(
            args.max_run_embedding_tokens, args.part_threshold, args.batch_chunks, args.batch_tokens
        )
        < 1
    ):
        parser.error("Limits must be positive")
    if args.batch_chunks > 1000 or args.batch_tokens > 10_000:
        parser.error("First-run limits cannot exceed 1000 texts / 10000 input tokens")
    with run_lock(REPORTS / "ingestion.lock"):
        counter = TokenCounter(REPORTS / "tokenizer" / "tokenizer.json")
        inventory_path = REPORTS / "pdf_inventory.json"
        inv = (
            inventory(counter, ROOT / "pdfs books", include_added=args.include_added_books)
            if args.inventory or args.include_added_books or not inventory_path.exists()
            else read_json(inventory_path)
        )
        for book in inv["books"]:
            with (ROOT / "pdfs books" / book["filename"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != book["file_hash"]:
                    raise ValueError("PDF changed; rerun with --inventory")
        plans = prepare(
            counter, inv, threshold=args.part_threshold, max_budget=args.max_run_embedding_tokens
        )
        report = read_json(REPORTS / "chunking_report.json")
        print(
            f"Selected books: {len(plans)}; planned input tokens: "
            f"{report['estimated_embedding_tokens']:,}; budget: "
            f"{args.max_run_embedding_tokens:,}; fits: {report['fits_budget']}",
            flush=True,
        )
        settings = get_settings()
        embedder = get_embedding_provider(batch_size=args.batch_chunks, max_attempts=1)
        runner = ResumableRunner(
            None,
            embedder,
            budget=args.max_run_embedding_tokens,
            max_chunks=args.batch_chunks,
            max_tokens=args.batch_tokens,
        )
        if not args.live:
            runner.report(plans, "local_preparation_only")
            return
        if not plans:
            runner.report(plans, "blocked_pdf_quality")
            raise Paused("No selected PDFs passed local extraction quality checks")
        if settings.voyage_model != "voyage-4-lite":
            raise Paused("This frozen plan requires voyage-4-lite / 1024 dimensions")
        if not settings.supabase_url or not settings.supabase_secret_key:
            runner.report(plans, "blocked_storage_configuration")
            raise Paused("Set SUPABASE_URL and SUPABASE_SECRET_KEY locally before live ingestion")
        if urlsplit(settings.supabase_url).hostname != "ivlmduwdkwgrxqxjjuyg.supabase.co":
            raise Paused("Storage URL does not match the selected Similia AI project")
        if not settings.voyage_api_key:
            raise Paused("VOYAGE_API_KEY is not configured")
        runner.sink = SupabaseSink(get_supabase_admin_client())
        try:
            runner.sink.preflight()  # No embeddings until the storage path is reachable.
        except Exception as exc:
            runner.report(plans, "blocked_storage_schema_or_permissions")
            raise Paused(
                f"Storage preflight failed ({type(exc).__name__}); "
                "knowledge tables and write/checkpoint persistence remain unverified"
            ) from None
        try:
            for plan in plans:
                if args.sample:
                    runner.run_book(plan, sample_limit=16)
                else:
                    if not runner.journal.get("sample:" + plan["plan_hash"]):
                        try:
                            runner.run_book(plan, sample_limit=16)
                        except Paused:
                            if not runner.journal.get("sample:" + plan["plan_hash"]):
                                raise
                    runner.run_book(plan)
        finally:
            runner.report(plans)


if __name__ == "__main__":
    try:
        main()
    except Paused as exc:
        print(f"PAUSED: {exc}", flush=True)
        raise SystemExit(2) from None
