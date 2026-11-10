"""The learning scripts (scripts/learn/) must keep working as the code changes.

Added 8 Nov 2026. They're study aids that run the real code, so if a refactor breaks one, the
user finds out from a failing test here, not mid-way through a learning session.
"""

from __future__ import annotations

import runpy

import pytest

from copilot.settings import REPO_ROOT

SNAPSHOT_DB = REPO_ROOT / "data" / "snapshot"
needs_snapshot = pytest.mark.skipif(
    not any(SNAPSHOT_DB.glob("*.parquet")), reason="needs the local snapshot"
)


@needs_snapshot
def test_session1_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(
        str(REPO_ROOT / "scripts" / "learn" / "session1_data_and_sql.py"), run_name="__main__"
    )
    out = capsys.readouterr().out
    for n in range(1, 8):
        assert f"STEP {n}:" in out
    assert "NOT refused" not in out  # every lock attack must be refused
    assert "BLOCKED: sql_fanout_sum" in out
    assert "filter added: MeetsMinK on vendor_revenue_summary" in out


def _run(name: str, capsys: pytest.CaptureFixture[str]) -> str:
    runpy.run_path(str(REPO_ROOT / "scripts" / "learn" / name), run_name="__main__")
    out = capsys.readouterr().out
    for n in range(1, 9):
        assert f"STEP {n}:" in out
    assert "Done." in out
    return out


@needs_snapshot
def test_session2_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run("session2_ml_tools.py", capsys)
    assert "WAPE  = 0.1153" in out  # the hand-computed naive backtest matches the tool's
    assert "safety stock if variability came from it: 0" in out


def test_session3_script_runs_every_step(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEARN_SKIP_EMBEDDINGS", "1")  # no embedding model in tests or CI
    out = _run("session3_rag.py", capsys)
    assert "132 chunks in all" in out
    assert "anonymous   44 of 132 chunks" in out


def test_session4_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run("session4_llm_layer.py", capsys)
    assert '"additionalProperties": false' in out  # the empty-box bug is shown, not hidden
    assert "repair_attempt logged = 1" in out


@needs_snapshot
def test_session5_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run("session5_agents.py", capsys)
    assert "-> revise_draft" in out and "-> guardian" in out
    assert "verified: True" in out


def test_session6_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run("session6_guardrails.py", capsys)
    assert "BLOCK     vendor email built on internal figures" in out
    assert "pending_approval = True" in out
    assert "decision = approved" in out


@needs_snapshot
def test_session7_script_runs_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run("session7_product_and_quality.py", capsys)
    assert "POST /ask with no key -> 401" in out
    assert "request 3: 429" in out
