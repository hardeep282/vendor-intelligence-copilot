"""Golden evaluation set: schema, loader and verifier.

Purpose : define what one golden question looks like and re-check it against the snapshot.
Inputs  : evals/datasets/golden_v1.jsonl and the DuckDB snapshot.
Outputs : typed `GoldenQuestion` objects; `verify()` re-executes every SQL and compares results.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel

from copilot.settings import REPO_ROOT

GOLDEN_PATH = REPO_ROOT / "evals" / "datasets" / "golden_v1.jsonl"
# v2 adds the 6 text-to-SQL trap questions from docs/specs/text_to_sql_safety.md on top of v1's
# 40 (v1 stays frozen so its history stays attached to the InsightService-era eval numbers).
GOLDEN_V2_PATH = REPO_ROOT / "evals" / "datasets" / "golden_v2.jsonl"

Category = Literal[
    "lookup",
    "aggregation",
    "comparison",
    "trend",
    "definition",
    "multi_hop",
    "out_of_scope",
    "adversarial",
]
Split = Literal["dev", "test", "adversarial"]
Expect = Literal["answer", "refuse", "block"]


class GoldenQuestion(BaseModel):
    id: str
    split: Split
    category: Category
    difficulty: Literal["easy", "medium", "hard"]
    question: str
    role: Literal["anonymous", "viewer", "analyst", "approver"] = "viewer"
    expect: Expect = "answer"
    sql: str | None = None  # verified SQL (None for definitions, out-of-scope, adversarial)
    expected_rows: list[dict[str, Any]] | None = None  # produced by executing `sql`
    reference_answer: str  # what a correct answer says (numbers come from expected_rows)
    answer_source: Literal["sql", "docs", "policy"]
    expected_tools: list[str] = []
    data_class: Literal["public", "internal", "confidential", "restricted"] = "internal"


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [GoldenQuestion.model_validate_json(line) for line in lines if line.strip()]


def run_rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    """Execute SQL and return rows as dicts with floats rounded to 2 dp (stable for comparison)."""
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(
            {
                c: (round(v, 2) if isinstance(v, float) else v)
                for c, v in zip(cols, row, strict=True)
            }
        )
    return out


def dataset_hash(path: Path = GOLDEN_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(con: duckdb.DuckDBPyConnection, questions: list[GoldenQuestion]) -> list[str]:
    """Re-run every SQL question; return a list of mismatch descriptions (empty = all verified)."""
    problems: list[str] = []
    for q in questions:
        if q.sql is None:
            continue
        got = json.loads(json.dumps(run_rows(con, q.sql), default=str))
        want = json.loads(json.dumps(q.expected_rows, default=str))
        if got != want:
            problems.append(f"{q.id}: stored result differs from a fresh execution")
    return problems
