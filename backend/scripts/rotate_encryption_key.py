"""Re-encrypt every stored doctor AI key with the current APP_ENCRYPTION_KEY.

Safe by default: without --apply it only counts what would change. It never prints a key,
a token or a user id. Run it after moving the old key into APP_ENCRYPTION_KEY_PREVIOUS and
putting the new key into APP_ENCRYPTION_KEY (see docs/production-runbook.md):

    uv run python scripts/rotate_encryption_key.py            # dry run
    uv run python scripts/rotate_encryption_key.py --apply    # rewrite the rows
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.vault import VaultError, rotate_secret  # noqa: E402
from app.services.supabase import get_supabase_admin_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the re-encrypted values")
    apply = parser.parse_args().apply
    db = get_supabase_admin_client()
    rows = db.table("user_ai_settings").select("practitioner_id,encrypted_api_key").execute().data
    changed = failed = 0
    for row in rows:
        try:
            fresh = rotate_secret(row["encrypted_api_key"])
        except VaultError:
            failed += 1
            continue
        if fresh != row["encrypted_api_key"]:
            changed += 1
            if apply:
                db.table("user_ai_settings").update({"encrypted_api_key": fresh}).eq(
                    "practitioner_id", row["practitioner_id"]
                ).execute()
    print(
        f"rows: {len(rows)}, re-encrypted: {changed if apply else 0}, "
        f"would change: {0 if apply else changed}, cannot decrypt: {failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
