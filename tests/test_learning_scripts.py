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
