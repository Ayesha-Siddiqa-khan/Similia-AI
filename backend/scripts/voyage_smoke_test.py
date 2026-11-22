"""Live Voyage AI embedding smoke test.

Reports embedding dimensions and tokens consumed for voyage-4-lite.
Makes a real API call, so it refuses to run unless:
  1. VOYAGE_API_KEY is configured (created in the MongoDB Atlas UI under
     "AI Model APIs" -> "Create model API key"), and
  2. you pass --yes to explicitly approve sending this tiny sample text.

Usage:
    uv run python scripts/voyage_smoke_test.py --yes
"""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="approve the live API call")
    args = parser.parse_args()

    if not os.environ.get("VOYAGE_API_KEY"):
        print("VOYAGE_API_KEY is not set (MongoDB Atlas -> AI Model APIs).")
        return 1
    if not args.yes:
        print("Refusing to make a live API call without --yes (user approval).")
        return 1

    from app.core.config import get_settings
    from app.services.embeddings import get_embedding_provider

    settings = get_settings()
    provider = get_embedding_provider()
    print(f"Model: {settings.voyage_model}")

    doc = provider.embed_documents(
        ["Aconitum napellus: restlessness and fear following exposure to cold wind."]
    )
    print(f"Document embedding dimensions: {len(doc.embeddings[0])}")
    print(f"Tokens consumed (document): {doc.total_tokens}")

    query_vector = provider.embed_query("Which remedy suits sudden fear with restlessness?")
    print(f"Query embedding dimensions: {len(query_vector)}")

    ok = len(doc.embeddings[0]) == provider.dimension and len(query_vector) == provider.dimension
    print("OK" if ok else "DIMENSION MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
