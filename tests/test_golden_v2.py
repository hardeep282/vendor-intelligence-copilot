"""Tests for golden v2 (v1 + the 6 text-to-SQL trap questions). v1 stays frozen and keeps its
own tests in test_golden.py unchanged; this file never touches golden_v1.jsonl."""

import json
import re

import pytest

from copilot.data.store import DB_NAME, connect
from copilot.evals.golden import GOLDEN_V2_PATH, dataset_hash, load_golden, verify
from copilot.guardrails.policy import load_policy
from copilot.settings import get_settings

QUESTIONS = load_golden(GOLDEN_V2_PATH)
# See the matching comment in test_golden.py -- checks the real database file, not the always-
# committed, licence-safe manifest, so this actually skips in CI instead of failing.
HAS_SNAPSHOT = (get_settings().snapshot_dir / DB_NAME).exists()


def test_forty_six_unique_questions() -> None:
    assert len(QUESTIONS) == 46
    assert len({q.id for q in QUESTIONS}) == 46


def test_v2_is_v1_plus_exactly_six_new_questions() -> None:
    from copilot.evals.golden import GOLDEN_PATH
    from copilot.evals.golden import load_golden as _load

    v1_ids = {q.id for q in _load(GOLDEN_PATH)}
    v2_ids = {q.id for q in QUESTIONS}
    assert v1_ids <= v2_ids
    assert v2_ids - v1_ids == {f"gq-04{n}" for n in range(1, 7)}


def test_golden_sql_is_select_only_on_catalogued_tables() -> None:
    policy = load_policy()
    for q in QUESTIONS:
        if q.sql is None:
            continue
        assert re.match(r"^\s*(SELECT|WITH)\b", q.sql, re.I), q.id
        assert not re.search(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|COPY)\b", q.sql, re.I
        )
        tables = re.findall(r"\b(?:FROM|JOIN)\s+([a-z_]+)", q.sql, re.I)
        for t in tables:
            assert t in policy.tables, f"{q.id} uses uncatalogued table {t}"
        for name in policy.restricted_names:
            assert name.lower() not in q.sql.lower(), f"{q.id} touches restricted name {name}"


def test_manifest_hash_matches_file() -> None:
    manifest = json.loads((GOLDEN_V2_PATH.parent / "golden_v2.manifest.json").read_text())
    assert manifest["sha256"] == dataset_hash(GOLDEN_V2_PATH)


@pytest.mark.skipif(not HAS_SNAPSHOT, reason="snapshot not built")
def test_every_stored_answer_re_executes_identically() -> None:
    assert verify(connect(), QUESTIONS) == []


# -- the 6 new trap questions specifically ---------------------------------------------------


def test_q1_2025_abstains_with_no_sql() -> None:
    q = next(q for q in QUESTIONS if q.id == "gq-042")
    assert q.expect == "refuse"
    assert q.sql is None
    assert q.expected_rows is None


def test_2023_vs_2024_comparison_is_a_partial_answer() -> None:
    q = next(q for q in QUESTIONS if q.id == "gq-043")
    assert q.expect == "answer"
    assert "2023" in q.reference_answer


def test_total_freight_matches_the_real_snapshot_figure() -> None:
    q = next(q for q in QUESTIONS if q.id == "gq-044")
    assert q.expected_rows == [{"total_freight": 1640474.69}]


def test_blended_margin_is_a_ratio_not_an_average() -> None:
    q = next(q for q in QUESTIONS if q.id == "gq-045")
    assert q.expected_rows == [{"blended_margin_pct": 28.72}]
    assert "AVG(BlendedMarginPct)" in q.reference_answer


def test_loss_making_and_dead_stock_are_reported_separately_not_summed() -> None:
    q = next(q for q in QUESTIONS if q.id == "gq-046")
    assert q.expected_rows == [{"loss_making_skus": 2127, "dead_stock_skus": 6334}]
    assert "8,461" in q.reference_answer and "never" in q.reference_answer
