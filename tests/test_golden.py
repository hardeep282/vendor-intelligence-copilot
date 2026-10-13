"""Tests for the golden set: structure, safety of its SQL and (with a snapshot) re-verification."""

import json
import re
from collections import Counter

import pytest

from copilot.data.store import connect
from copilot.evals.golden import GOLDEN_PATH, dataset_hash, load_golden, verify
from copilot.guardrails.policy import load_policy
from copilot.settings import get_settings

QUESTIONS = load_golden()
HAS_SNAPSHOT = (get_settings().snapshot_dir / "MANIFEST.json").exists()


def test_forty_unique_questions() -> None:
    assert len(QUESTIONS) == 40
    assert len({q.id for q in QUESTIONS}) == 40


def test_every_category_is_covered() -> None:
    cats = Counter(q.category for q in QUESTIONS)
    assert set(cats) == {
        "lookup", "aggregation", "comparison", "trend",
        "definition", "multi_hop", "out_of_scope", "adversarial",
    }  # fmt: skip


def test_splits_and_expectations() -> None:
    splits = Counter(q.split for q in QUESTIONS)
    assert splits == {"dev": 27, "test": 10, "adversarial": 3}
    assert all(q.expect == "block" for q in QUESTIONS if q.category == "adversarial")
    assert all(q.expect == "refuse" for q in QUESTIONS if q.category == "out_of_scope")


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
    manifest = json.loads((GOLDEN_PATH.parent / "golden_v1.manifest.json").read_text())
    assert manifest["sha256"] == dataset_hash()


@pytest.mark.skipif(not HAS_SNAPSHOT, reason="snapshot not built")
def test_every_stored_answer_re_executes_identically() -> None:
    assert verify(connect(), QUESTIONS) == []
