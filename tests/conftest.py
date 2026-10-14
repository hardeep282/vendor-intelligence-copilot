"""Session-wide test fixtures.

Day 7 step 6: `InputGate`'s default `SpendTracker` persists today's spend per role to a real
on-disk file (`data/spend/daily_spend.json`) so a role's daily cap survives a process restart
within the same day -- exactly the durability the real app needs, and exactly what would make
tests leak spend into each other (and into the real repo's `data/` directory) if left pointed at
that real path: dozens of orchestrator tests construct an `Orchestrator` with no explicit
`input_gate`, each getting a default `InputGate()` whose `SpendTracker` would otherwise share
one file and one running total across the entire test session, eventually tripping the
`daily_spend_cap_usd` check for reasons that have nothing to do with what any individual test is
checking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot.guardrails import input_gate as input_gate_module


@pytest.fixture(autouse=True)
def _isolated_spend_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own empty spend file instead of the real repo path -- autouse so no
    test has to remember to ask for it, and so a test that *does* want to exercise the real
    default path can still pass its own `SpendTracker`/`path=` explicitly without this fixture
    getting in the way (it only changes what the *unpatched* default resolves to).
    """
    monkeypatch.setattr(
        input_gate_module, "DEFAULT_SPEND_LOG_PATH", tmp_path / "daily_spend.json"
    )
