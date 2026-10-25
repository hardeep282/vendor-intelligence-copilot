"""Generate question -> SQL pairs from parameterized templates for the Day 9 fine-tuning set.

Purpose : CLI entrypoint for `copilot.sql.pair_generation` (read its docstring for the full
          design). Needs a built snapshot, same licence rule as every other "real data" script
          in this repo (ADR-002) -- it reads real vendor names from the connected database at
          generation time rather than hardcoding any.
Run     : uv run python scripts/generate_sql_pairs.py [--target 400] [--seed 42]
          (needs a built snapshot: scripts/build_snapshot.py "path/to/Vendor_Summary.xlsx" first)
Outputs : evals/datasets/sql_pairs_v2.jsonl (one execution-verified, validator-passed pair per
          line) and a sibling manifest (count, per-category/table breakdown, dataset hash)
          mirroring golden_v1's own manifest pattern.
Versions: v1 (kept, unchanged) wrote stored vendor casing into the SQL while the question showed
          title case -- a target the model could not infer from its prompt. v2 matches vendors
          case-insensitively on the name exactly as the question shows it; same seed, same 400
          questions, same result rows (see docs/BUILD_LOG.md, Day 9 casing fix).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from copilot.settings import REPO_ROOT, get_settings
from copilot.sql.pair_generation import (
    Pair,
    category_breakdown,
    generate_candidates,
    table_breakdown,
    vendor_names,
    verify_and_filter,
)

OUT_PATH = REPO_ROOT / "evals" / "datasets" / "sql_pairs_v2.jsonl"


def _dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_path_for(out_path: Path) -> Path:
    """sql_pairs_v2.jsonl -> sql_pairs_v2.manifest.json, next to it. Derived from --out rather
    than a fixed constant, so writing to a different file never overwrites another version's
    manifest."""
    return out_path.with_name(out_path.stem + ".manifest.json")


def write_dataset(pairs: list[Pair], out_path: Path = OUT_PATH) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, pair in enumerate(pairs, start=1):
            row = {
                "id": f"sqlgen-{i:04d}",
                "question": pair.question,
                "sql": pair.sql,
                "role": pair.role,
                "category": pair.category,
                "table": pair.table,
                "source": "template",
            }
            f.write(json.dumps(row) + "\n")

    manifest = {
        "count": len(pairs),
        "by_category": category_breakdown(pairs),
        "by_table": table_breakdown(pairs),
        "sha256": _dataset_hash(out_path),
    }
    manifest_path_for(out_path).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=400, help="pairs to keep (300-500 per spec)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    from copilot.data.store import connect  # local import: needs a built snapshot to succeed

    settings = get_settings()
    if not (settings.snapshot_dir / "MANIFEST.json").exists():
        raise SystemExit(
            'No snapshot found. Run scripts/build_snapshot.py "path/to/Vendor_Summary.xlsx" '
            "first -- this script reads real vendor names and executes against the real "
            "snapshot, same licence-safe rule as everywhere else (ADR-002)."
        )

    con = connect()
    rng = random.Random(args.seed)
    vendors = vendor_names(con)
    candidates = generate_candidates(con, rng, vendors)
    kept, report = verify_and_filter(con, candidates)

    rng.shuffle(kept)
    sample = kept[: args.target]

    manifest = write_dataset(sample, args.out)

    print(f"candidates generated    : {report.candidates}")
    print(f"failed execution        : {report.execution_failed}")
    print(f"failed safety validator : {report.validator_failed}")
    print(f"passed both filters     : {report.kept}")
    print(f"written (sampled to --target={args.target}): {len(sample)}")
    print(f"by category: {manifest['by_category']}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
