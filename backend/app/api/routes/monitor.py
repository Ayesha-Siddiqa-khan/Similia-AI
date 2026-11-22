"""Read-only views of existing local ingestion artifacts. No provider calls."""

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.ingestion.local import REPORTS
from app.ai.rag.guard import embedding_paused
from app.api.auth import require_operator

router = APIRouter(
    prefix="/api/monitor", tags=["monitor"], dependencies=[Depends(require_operator)]
)


def artifact(name: str) -> dict[str, Any]:
    try:
        return json.loads((REPORTS / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Ingestion report is unavailable") from None


def checkpoint(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k not in ("completed_batch_ids", "last_batch_id")}


@router.get("/snapshot")
def snapshot() -> dict[str, Any]:
    inv = artifact("pdf_inventory.json")
    progress = artifact("ingestion_progress.json")
    manifest = artifact("run_manifest.json")
    books = []
    for b in progress.get("books", []):
        safe = {k: v for k, v in b.items() if k not in ("pending_chunk_indices", "parts")}
        safe["current_checkpoint"] = checkpoint(b.get("current_checkpoint", {}))
        safe["parts"] = [
            {**p, "checkpoint": checkpoint(p.get("checkpoint", {}))} for p in b.get("parts", [])
        ]
        books.append(safe)
    usage = {k: v for k, v in progress.get("usage", {}).items() if k != "books"}
    inventory = [
        {
            k: v
            for k, v in b.items()
            if k
            in (
                "file_hash",
                "filename",
                "title",
                "author",
                "category",
                "pdf_bytes",
                "text_bytes",
                "total_pages",
                "original_tokens",
                "quality_ok",
            )
        }
        | {
            "selected": b["file_hash"] in inv.get("selected_hashes", []),
            "priority": manifest.get("selected_hashes", []).index(b["file_hash"]) + 1
            if b["file_hash"] in manifest.get("selected_hashes", [])
            else None,
        }
        for b in inv.get("books", [])
    ]
    return {
        "timestamp": progress.get("timestamp"),
        "status": manifest.get("status"),
        # The live provider stop (database flag): this, not the old manifest, blocks search.
        "provider_paused": embedding_paused(),
        "inventory": inventory,
        "books": books,
        "usage": usage,
        "budget": manifest.get("cumulative_pipeline_cap"),
        "reserve": manifest.get("reserved_tokens_outside_pipeline_cap"),
        "required_action": manifest.get("required_action"),
        "capabilities": {
            "analyse": False,
            "preview": True,
            "start": False,
            "pause": False,
            "resume": False,
            "retry": False,
            "category_update": False,
        },
        "control_reason": (
            "Phase 2B is controlled by the budgeted CLI; "
            "safe HTTP control endpoints are not implemented."
        ),
        "source": "local_checkpoint_reports",
    }


@router.get("/chunks/{file_hash}")
def chunks(
    file_hash: str,
    q: str = Query(default="", max_length=200),
    section: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    inv = artifact("pdf_inventory.json")
    if not re.fullmatch(r"[a-f0-9]{64}", file_hash) or file_hash not in inv.get(
        "selected_hashes", []
    ):
        raise HTTPException(404, "No selected chunk plan for this book")
    plan_path: Path = REPORTS / "sources" / file_hash / "plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Frozen chunk plan is unavailable") from None
    progress = artifact("ingestion_progress.json")
    book = next((b for b in progress.get("books", []) if b["file_hash"] == file_hash), {})
    pending = set(book.get("pending_chunk_indices", []))
    rows = [
        c
        for c in plan["chunks"]
        if q.casefold() in c["content"].casefold()
        and section.casefold() in str(c["metadata"].get("section", "")).casefold()
    ]
    items = [
        {
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "token_count": c["token_count"],
            "byte_count": len(c["content"].encode("utf-8")),
            "metadata": c["metadata"],
            "embedding_status": ("stored" if c["chunk_index"] not in pending else "pending")
            if book
            else "unknown",
        }
        for c in rows[offset : offset + limit]
    ]
    return {
        "items": items,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "statistics": {
            k: book.get(k)
            for k in (
                "minimum_chunk_tokens",
                "maximum_chunk_tokens",
                "average_chunk_tokens",
                "median_chunk_tokens",
            )
        },
    }
