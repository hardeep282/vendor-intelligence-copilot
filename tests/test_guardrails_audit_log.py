"""Tests for the Guardian's audit log (Day 7 step 3)."""

from __future__ import annotations

from pathlib import Path

from copilot.guardrails.audit_log import log_decision, read_decisions
from copilot.guardrails.guardian import Finding, GuardianVerdict


def _verdict(outcome: str = "block") -> GuardianVerdict:
    return GuardianVerdict(
        outcome=outcome,  # type: ignore[arg-type]
        reason_codes=["canary_leak"],
        findings=[Finding(code="canary_leak", outcome="block", detail="x")],  # type: ignore[arg-type]
        safe_answer="blocked",
        policy_version=1,
    )


def test_log_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "guardian_log.jsonl"
    ok = log_decision(_verdict(), question="q1", role="viewer", path=path)
    assert ok is True
    rows = read_decisions(path)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "block"
    assert rows[0]["question"] == "q1"
    assert rows[0]["role"] == "viewer"


def test_appends_not_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "guardian_log.jsonl"
    log_decision(_verdict("block"), question="q1", role="viewer", path=path)
    log_decision(_verdict("allow"), question="q2", role="analyst", path=path)
    rows = read_decisions(path)
    assert len(rows) == 2
    assert [r["outcome"] for r in rows] == ["block", "allow"]


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_decisions(tmp_path / "does_not_exist.jsonl") == []


def test_write_failure_returns_false(tmp_path: Path) -> None:
    # A path whose parent is actually a file (not a directory) can't be mkdir'd into.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    bad_path = blocker / "sub" / "guardian_log.jsonl"
    assert log_decision(_verdict(), question="q", role="viewer", path=bad_path) is False


def test_review_id_defaults_to_none(tmp_path: Path) -> None:
    # Day 8, ADR-006 q2: a non-escalate decision has nothing to review, so nothing to join on.
    path = tmp_path / "guardian_log.jsonl"
    log_decision(_verdict("block"), question="q", role="viewer", path=path)
    assert read_decisions(path)[0]["review_id"] is None


def test_review_id_is_recorded_when_given(tmp_path: Path) -> None:
    path = tmp_path / "guardian_log.jsonl"
    log_decision(_verdict("escalate"), question="q", role="viewer", path=path, review_id="rid-123")
    row = read_decisions(path)[0]
    assert row["outcome"] == "escalate"
    assert row["review_id"] == "rid-123"
