"""Day 7 step 6: the input gate -- checks that run on the user's question *before* the
Orchestrator ever sees it (master prompt D2/C4's "input checks" half of defence in depth; the
Guardian, `copilot.guardrails.guardian`, is the output half).

Purpose : stop a bad, abusive, or runaway request at the door -- cheaply, deterministically, and
          before a single LLM call or specialist run has spent anything.
Inputs  : the raw question text and the requesting `Role`.
Outputs : a `GateVerdict` -- `outcome` (`allow`/`block`), every `Finding` that fired, and a
          `message` safe to show the user when blocked.

**Six checks, cheapest first** (sprint doc D7 step 6's exact list): kill switch (one in-memory
flag), input length (a `len()` call), injection heuristics (a handful of regexes), scope (a
couple more regexes), rate limit (an in-memory sliding window, no I/O), daily spend cap (the one
check that touches disk, via `SpendTracker`) -- same "cheapest first, most expensive last" shape
`Guardian.review` already uses on the output side, and for the same reason: a cheap check that
already blocks means the expensive one never has to run.

**Why no injection *classifier*:** the sprint doc's one Day 7 cut-first item is exactly this --
"keep heuristics and least-privilege tools." A classifier is a second model call per request
(cost, latency, and a new thing that itself needs evaluating); the heuristics below catch the
common, blunt injection phrasings for free. `_check_injection`'s docstring says where the real
stopgap is: least-privilege tools (the role-scoped schema in `copilot.sql.schema`, `Disclosure
Policy.can_view`, the Guardian's own role/audience checks) mean even a cleverly-worded injection
that slips past these regexes still can't make a specialist return data the role isn't allowed
to see, or make the Guardian wave through a draft it would otherwise catch.

**Why BLOCK only, no REDACT/ESCALATE:** those two outcomes make sense once there's an answer to
partially salvage (the Guardian's job). A bad *input* has nothing worth partially keeping --
either it's fine to run, or the Orchestrator never starts.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from copilot.guardrails.policy import Role
from copilot.settings import REPO_ROOT, get_settings

GateOutcome = Literal["allow", "block"]

DEFAULT_SPEND_LOG_PATH = REPO_ROOT / "data" / "spend" / "daily_spend.json"

# Blunt, common injection phrasings -- not exhaustive (that's the classifier this step cuts),
# but free and catches the phrasing an actual careless/adversarial user types most often.
_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"(?i)\bignore\s+(all\s+|the\s+)?(previous|prior|above|earlier)\s+instructions?\b"
    ),
    "disregard_instructions": re.compile(
        r"(?i)\bdisregard\s+(all\s+|the\s+)?(previous|prior|above|earlier|system)\s+"
        r"(instructions?|prompt)\b"
    ),
    "reveal_system_prompt": re.compile(
        r"(?i)\b(reveal|show|print|repeat|output)\s+(me\s+)?your\s+(system\s+)?prompt\b"
    ),
    "forget_everything": re.compile(r"(?i)\bforget\s+(everything|all\s+(your\s+)?instructions)\b"),
    "new_persona": re.compile(
        r"(?i)\byou\s+are\s+now\s+|"
        r"\bpretend\s+(you('re| are)\s+)?|\bact\s+as\s+(if\s+you('re| are)\s+)?|"
        r"\b(DAN|developer)\s+mode\b|\bjailbreak\b"
    ),
    "override_instructions": re.compile(r"(?i)\boverride\s+(your\s+)?(system\s+)?instructions?\b"),
}

# A deliberately small, heuristic scope check: this app answers vendor/procurement/supply-chain
# questions. A question matching one of these off-topic request shapes is almost certainly not
# that, whatever it's actually about -- and it costs nothing to say so before spending an LLM
# call finding out. Anything else (including questions this heuristic can't classify either way)
# passes through -- false negatives here are the Orchestrator's/Guardian's problem, not this
# check's; false positives on a real vendor question would be worse than letting an edge case
# through.
_OFF_TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "write_me_a_poem": re.compile(r"(?i)\bwrite\s+(me\s+)?(a\s+)?(poem|song|haiku|lyrics)\b"),
    "tell_me_a_joke": re.compile(r"(?i)\btell\s+(me\s+)?(a\s+)?joke\b"),
    "write_code_for": re.compile(
        r"(?i)\bwrite\s+(me\s+)?(a\s+|some\s+)?(python|javascript|code|script|function)\b.*"
        r"\b(unrelated|not\s+about|outside)\b"
    ),
    "general_weather": re.compile(r"(?i)\bwhat('s| is)\s+the\s+weather\b"),
    # Master prompt C4's privacy-leakage suite names "other users' memory" as an attack
    # category this app must refuse: there is no cross-user/cross-thread memory store at all
    # (`Orchestrator`'s checkpointer is keyed by `thread_id`, never exposed across callers), so
    # a request for it is refused as out-of-scope rather than routed anywhere that could answer.
    "other_users_data": re.compile(
        r"(?i)\bwhat\s+(did|has)\s+(another|other|a\s+different)\s+user\b|"
        r"\b(another|other)\s+user'?s?\s+(conversation|questions?|history|memory)\b"
    ),
}


class Finding(BaseModel):
    code: str
    outcome: GateOutcome
    detail: str


class GateVerdict(BaseModel):
    outcome: GateOutcome
    reason_codes: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    message: str = ""


_BLOCK_MESSAGE = (
    "This request was stopped before it reached the system. Reason code(s): {codes}. "
    "Rephrase your question, or contact an administrator if you believe this is wrong."
)


class RateLimiter:
    """An in-memory sliding-window limiter, one window per role. No persistence -- a process
    restart resets everyone's count, which is fine for a per-role request-rate guard (unlike the
    spend cap, which has to survive a restart within the same day -- `SpendTracker` below).
    """

    def __init__(self, max_per_minute: int) -> None:
        self._max_per_minute = max_per_minute
        self._hits: dict[str, list[float]] = {}

    def allow(self, role: str) -> bool:
        """Records this call as a hit and returns whether it's within the limit. Checking and
        recording in one step (rather than a separate `.record()`) keeps the window itself the
        single source of truth -- a caller can't check, decide not to proceed, and leave a stale
        hit counted, or forget to record and silently bypass the limit.
        """
        now = time.monotonic()
        window_start = now - 60.0
        hits = [t for t in self._hits.get(role, []) if t >= window_start]
        allowed = len(hits) < self._max_per_minute
        hits.append(now)
        self._hits[role] = hits
        return allowed


class SpendTracker:
    """Tracks today's cumulative spend per role in a small JSON file (`data/spend/
    daily_spend.json` by default) -- has to survive a process restart within the same day, so
    (unlike `RateLimiter`) this one does touch disk. `record()` is called by whatever ran the
    actual LLM calls (the Orchestrator, after `answer()` returns its `total_cost_usd`) -- the
    input gate itself only ever reads this to decide whether *today's next* request may start;
    it never knows the cost of the request it's currently gating.
    """

    def __init__(self, path: Path | None = None) -> None:
        # Resolved at call time (a plain module-global lookup in the body), not bound as a
        # default-argument value -- so a test's `monkeypatch.setattr(input_gate,
        # "DEFAULT_SPEND_LOG_PATH", ...)` actually takes effect for every `SpendTracker()`
        # constructed afterwards, including the one `InputGate.__init__` builds by default.
        self._path = path if path is not None else DEFAULT_SPEND_LOG_PATH

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _load(self) -> dict[str, dict[str, float]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def spent_today(self, role: str) -> float:
        data = self._load()
        return float(data.get(self._today_key(), {}).get(role, 0.0))

    def record(self, role: str, cost_usd: float) -> bool:
        """Adds `cost_usd` to today's running total for `role`. Returns `True` on a successful
        write, `False` on a logging failure (disk full, permissions) -- same never-raises
        contract `copilot.guardrails.audit_log.log_decision` already established, for the same
        reason: a spend-tracking write failure must not itself crash a request that already ran.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = self._load()
            today = data.setdefault(self._today_key(), {})
            today[role] = today.get(role, 0.0) + cost_usd
            self._path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            return False
        return True


class InputGate:
    """Stateless apart from the rate limiter/spend tracker it was built with -- mirrors
    `Guardian`'s own construction pattern (expensive-ish setup once, cheap calls after).
    `_rate_limiter` is process-local by design (see `RateLimiter`'s docstring); `_spend_tracker`
    is the one piece of state that has to be shared/durable, so it's file-backed.
    """

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        spend_tracker: SpendTracker | None = None,
        max_question_chars: int | None = None,
        daily_spend_cap_usd: float | None = None,
        kill_switch_enabled: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._rate_limiter = rate_limiter or RateLimiter(settings.rate_limit_per_minute)
        self._spend_tracker = spend_tracker or SpendTracker()
        self._max_question_chars = max_question_chars or settings.max_question_chars
        self._daily_spend_cap_usd = (
            daily_spend_cap_usd if daily_spend_cap_usd is not None else settings.daily_spend_cap_usd
        )
        self._kill_switch_enabled = (
            kill_switch_enabled if kill_switch_enabled is not None else settings.kill_switch_enabled
        )

    def review(self, question: str, role: Role) -> GateVerdict:
        findings: list[Finding] = [
            *self._check_kill_switch(),
            *self._check_length(question),
            *self._check_injection(question),
            *self._check_scope(question),
            *self._check_rate_limit(role),
            *self._check_spend_cap(role),
        ]
        if not findings:
            return GateVerdict(outcome="allow")

        # Every finding here is "block" (see module docstring for why there's no redact/escalate
        # on the input side) -- any finding at all means the outcome is "block".
        reason_codes = [f.code for f in findings]
        return GateVerdict(
            outcome="block",
            reason_codes=reason_codes,
            findings=findings,
            message=_BLOCK_MESSAGE.format(codes=", ".join(reason_codes)),
        )

    # -- checks, cheapest first -------------------------------------------------------------

    def _check_kill_switch(self) -> list[Finding]:
        if self._kill_switch_enabled:
            return [
                Finding(
                    code="kill_switch_engaged",
                    outcome="block",
                    detail="the kill switch is enabled -- every request is blocked regardless "
                    "of anything else until an operator turns it back off",
                )
            ]
        return []

    def _check_length(self, question: str) -> list[Finding]:
        if len(question) > self._max_question_chars:
            return [
                Finding(
                    code="input_too_long",
                    outcome="block",
                    detail=f"question is {len(question)} chars, over the "
                    f"{self._max_question_chars}-char limit",
                )
            ]
        return []

    def _check_injection(self, question: str) -> list[Finding]:
        findings = []
        for name, pattern in _INJECTION_PATTERNS.items():
            if pattern.search(question):
                findings.append(
                    Finding(
                        code=f"injection_heuristic:{name}",
                        outcome="block",
                        detail=f"question matches the '{name}' prompt-injection heuristic",
                    )
                )
        return findings

    def _check_scope(self, question: str) -> list[Finding]:
        for name, pattern in _OFF_TOPIC_PATTERNS.items():
            if pattern.search(question):
                return [
                    Finding(
                        code=f"out_of_scope:{name}",
                        outcome="block",
                        detail=f"question matches the '{name}' out-of-scope pattern -- this "
                        "system answers vendor/procurement/supply-chain questions",
                    )
                ]
        return []

    def _check_rate_limit(self, role: Role) -> list[Finding]:
        if not self._rate_limiter.allow(role):
            return [
                Finding(
                    code="rate_limit_exceeded",
                    outcome="block",
                    detail=f"role '{role}' exceeded its requests-per-minute limit",
                )
            ]
        return []

    def _check_spend_cap(self, role: Role) -> list[Finding]:
        if self._spend_tracker.spent_today(role) >= self._daily_spend_cap_usd:
            return [
                Finding(
                    code="daily_spend_cap_exceeded",
                    outcome="block",
                    detail=f"role '{role}' has already spent its ${self._daily_spend_cap_usd:.2f} "
                    "daily cap",
                )
            ]
        return []

    def record_spend(self, role: Role, cost_usd: float) -> bool:
        """The other half of the spend cap: called by whoever actually ran the request (the
        Orchestrator, after `answer()` has its real `total_cost_usd`) to add to today's running
        total. Exposed here rather than making callers reach into `self._spend_tracker` directly
        -- `InputGate` is the one object a caller needs to hold.
        """
        return self._spend_tracker.record(role, cost_usd)


__all__ = [
    "DEFAULT_SPEND_LOG_PATH",
    "Finding",
    "GateOutcome",
    "GateVerdict",
    "InputGate",
    "RateLimiter",
    "SpendTracker",
]
