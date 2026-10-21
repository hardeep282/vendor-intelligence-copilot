"""Day 7 step 3: an append-only audit log for every Guardian decision.

Purpose : a durable, independent record of every ALLOW/REDACT/BLOCK/ESCALATE decision (master
          prompt C4: "Decision recorded ... in an audit log"). Independent of LangSmith on
          purpose -- traces can be sampled, redacted or rotated (Day 7 step 7); this file is the
          compliance-grade record that must survive all of that.
Inputs  : a `GuardianVerdict` plus the question/role it was decided for.
Outputs : one JSON line appended to `data/audit/guardian_log.jsonl` per decision.

Local, append-only, never committed -- same convention `copilot.ml.run_log`'s CSV already
established for this repo's local-only run records; unlike `*.csv`, `.jsonl` had no existing
blanket rule, so this file's own `.gitignore` entry (`data/audit/*.jsonl`) was added alongside
it.

**Day 7 step 5: `log_approval`.** A human approver's approve/edit/reject decision on an Action
draft is a different kind of event from a Guardian check (`log_decision`'s row) -- there's no
`GuardianVerdict` to log for it (an edit gets re-reviewed through the Guardian separately, which
produces its own `log_decision` row), just who decided what. Kept in the same file/log so one
`read_decisions` call still gives the full story for a thread, distinguished by `"event"`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from copilot.guardrails.guardian import GuardianVerdict
from copilot.settings import REPO_ROOT

DEFAULT_AUDIT_LOG_PATH = REPO_ROOT / "data" / "audit" / "guardian_log.jsonl"


def log_decision(
    verdict: GuardianVerdict,
    *,
    question: str,
    role: str,
    path: Path = DEFAULT_AUDIT_LOG_PATH,
    review_id: str | None = None,
) -> bool:
    """Append one row. Returns True on a successful write, False on a logging failure (disk
    full, permissions) -- never raises into the caller's request path, because an audit-log
    write problem must not itself take down an answer that already passed the Guardian. A
    caller/test can still notice via the return value without the Guardian call becoming
    load-bearing on filesystem health.

    `review_id` (Day 8, ADR-006 question 2): the orchestrator passes a fresh uuid4 string here
    whenever `verdict.outcome == "escalate"`, so this row and the `PendingReview` object the
    caller gets back both carry the same id -- the join key a future reviewer (or, today, anyone
    grepping the log by hand) uses to find the exact decision a `pending_review` status refers
    to. `None` for every non-escalate decision (nothing to review, nothing to join on).
    """
    row = {
        "ts": time.time(),
        "event": "guardian_decision",
        "question": question,
        "role": role,
        "outcome": verdict.outcome,
        "reason_codes": verdict.reason_codes,
        "policy_version": verdict.policy_version,
        "findings": [f.model_dump() for f in verdict.findings],
        "review_id": review_id,
    }
    return _append_row(row, path)


def log_approval(
    *,
    question: str,
    role: str,
    decision: str,
    final_answer: str,
    path: Path = DEFAULT_AUDIT_LOG_PATH,
) -> bool:
    """Append one approver-decision row (Day 7 step 5: the Action-draft approve/edit/reject
    flow). `role` here is the *approver's* role (already checked to be `approver`/`admin` by
    `Orchestrator.resume_approval` before this is ever called), not the original requester's
    role that `log_decision` records -- same never-raises-into-the-caller contract as
    `log_decision`, for the same reason (an audit-write failure must not block a decision that
    already happened).
    """
    row = {
        "ts": time.time(),
        "event": "approval_decision",
        "question": question,
        "role": role,
        "decision": decision,
        "final_answer": final_answer,
    }
    return _append_row(row, path)


def _append_row(row: dict[str, object], path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        return False
    return True


def read_decisions(path: Path = DEFAULT_AUDIT_LOG_PATH) -> list[dict[str, object]]:
    """Read every logged decision back, oldest first. Used by tests and by `scripts/` reports;
    returns `[]` for a log that doesn't exist yet rather than raising.
    """
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = ["DEFAULT_AUDIT_LOG_PATH", "log_approval", "log_decision", "read_decisions"]
