"""CLI for the fine-tuning dataset module.

Run from ``backend``:

    uv run --offline --no-sync python -m app.ai.finetune audit
    uv run --offline --no-sync python -m app.ai.finetune export --dry-run
    uv run --offline --no-sync python -m app.ai.finetune export
    uv run --offline --no-sync python -m app.ai.finetune verify
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ai.finetune.config import DATASET_ROOT, PILOT_TARGET
from app.ai.finetune.pipeline import run_export, verify_export


def _summary(report: dict) -> dict:
    return {
        "verdict": report["verdict"],
        "licences": {
            key: report["licences"][key]
            for key in ("exportable", "blocked", "suppressed", "quality_excluded")
        },
        "corpus": report["corpus"],
        "duplicates": {
            "groups": report["duplicates"]["groups"],
            "redundant_chunks": report["duplicates"]["redundant_chunks"],
        },
        "splits": report["splits"],
        "cpt": report["cpt"],
        "sft": {
            "target": report["sft"]["target"],
            "examples": report["sft"]["examples"],
            "verified": report["sft"]["verified"],
            "failed": report["sft"]["failed"],
            "failure_reasons": report["sft"]["failure_reasons"],
            "shortfall": report["sft"]["shortfall"],
            "per_book": report["sft"]["per_book"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.ai.finetune",
        description="Prepare fine-tuning datasets from the Similia AI knowledge base (read-only).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Compute the export plan without writing files.")
    audit.add_argument("--target", type=int, default=PILOT_TARGET)

    export = subparsers.add_parser("export", help="Write CPT and SFT datasets locally.")
    export.add_argument("--output", type=Path, default=DATASET_ROOT / "v1")
    export.add_argument("--target", type=int, default=PILOT_TARGET)
    export.add_argument("--dry-run", action="store_true")

    verify = subparsers.add_parser("verify", help="Re-check pilot answers against live sources.")
    verify.add_argument("--output", type=Path, default=DATASET_ROOT / "v1")

    args = parser.parse_args(argv)

    if args.command == "audit":
        report = run_export(target=args.target, dry_run=True)
        print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
        return 0

    if args.command == "export":
        report = run_export(output_dir=args.output, target=args.target, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
        else:
            print(f"Dataset written to {args.output}")
            print(f"SFT examples: {report['sft']['examples']}")
            print(f"Verdict: {report['verdict']}")
            print("No data was uploaded and no model training was started.")
        return 0

    result = verify_export(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
