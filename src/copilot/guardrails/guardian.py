"""Day 7 steps 1, 3 and 4's core: the Guardian -- the single mandatory final pass every answer
and action draft goes through before the user sees it (master prompt C4).

Purpose : run the role/audience/provenance/raw-row/secret/PII/grounding checks C4 lists, in
          cheapest-first order, against one finished `OrchestratorResult`-shaped object, and
          turn the result into one of four outcomes with reason codes.
Inputs  : anything matching `_Reviewable` below (role, answer, the specialists' `AgentResult`s,
          the Verifier's `verified` flag) and a `DisclosurePolicy` (Day 1).
Outputs : a `GuardianVerdict` -- `outcome`, every `Finding` that fired, the `reason_codes` for
          the ones that decided the outcome, and `safe_answer` -- what the user is actually
          shown (the real answer on ALLOW, a redacted copy on REDACT, a safe generic message on
          BLOCK/ESCALATE). `copilot.agents.orchestrator._guardian` is the one call site that
          matters in production; `docs/HANDOFF.md`/the Day 7 ADR explain why.

**Why a Protocol instead of importing `OrchestratorResult`:** `orchestrator.py` is the only
caller and needs to import this module (`finalize -> guardian -> END`, Day 7 step 4) -- importing
`OrchestratorResult` here would make that a circular import. `_Reviewable` names exactly the four
fields this module reads; `OrchestratorResult` satisfies it structurally, with no import needed
in either direction.

**Why no LLM call here:** master prompt C4 calls for "deterministic first, then a small
classifier or LLM check ... for semantic leaks and safety." Addendum A1's Day-10-minimum
guardrails row asks for input checks, output checks and a fail-closed disclosure policy -- it
does not ask for a second LLM judging the Guardian's own output, and the sprint doc's one
Day 7 cut-first item is exactly the other semantic layer (the injection *classifier*, see
`copilot.guardrails.input_gate`). So every check below is a regex, a policy-table lookup, or a
`set` comparison -- fast, deterministic, and testable without an API key, which matters because
the Guardian is the one node NOTHING may route around (step 4's topology test).

**Severity ordering:** `block` > `escalate` > `redact` > `allow` -- the worst finding decides the
outcome, but every finding (not just the worst) is kept in `GuardianVerdict.findings` and in
`reason_codes`, because the audit log (step 3, `copilot.guardrails.audit_log`) should show
everything that fired, not just the one that won.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from copilot.agents.contracts import AgentResult
from copilot.guardrails.pii import find_pii
from copilot.guardrails.policy import DataClass, DisclosurePolicy, Role, load_policy
from copilot.guardrails.secret_patterns import SECRET_PATTERNS

GuardianOutcome = Literal["allow", "redact", "block", "escalate"]

_SEVERITY: dict[GuardianOutcome, int] = {"allow": 0, "redact": 1, "escalate": 2, "block": 3}

# Secret patterns: cheap regexes for the handful of credential shapes this project's own
# .env.example documents (Anthropic, AWS, LangSmith/generic bearer tokens) -- not a general
# secret scanner (that's gitleaks's job, already in pre-commit/CI per ADR-004); this one runs
# on LLM *output*, which gitleaks never sees.
# SECRET_PATTERNS itself lives in `copilot.guardrails.secret_patterns` (a leaf module, no
# project imports) -- Day 7 step 7's `trace_masking.py` needs the exact same patterns, and
# importing them from here directly would create a real import cycle through `AgentResult`
# above. Re-exported here so existing `from copilot.guardrails.guardian import SECRET_PATTERNS`
# usage (and this module's own `_check_secrets`) keeps working unchanged.

# A suspected raw row-level dump: 10+ consecutive pipe- or tab-delimited lines with 3+ fields
# each. A short illustrative markdown table (a handful of summary rows) never matches; a real
# row-level export pasted into an answer does. Guardian only ever sees the final answer text,
# not the SQL result set itself -- see ADR-006 for why this heuristic is the Day 7 minimum
# rather than a real row-count check threaded through `AgentResult`.
RAW_ROW_PATTERN = re.compile(
    r"(?:^|\n)(?:[^\n|\t]+[|\t]){2,}[^\n|\t]+" r"(?:\n(?:[^\n|\t]+[|\t]){2,}[^\n|\t]+){9,}"
)


class _Reviewable(Protocol):
    """Structural shape the Guardian needs -- see module docstring for why this isn't an import
    of `OrchestratorResult`.
    """

    role: Role
    answer: str | None
    results: list[AgentResult]
    verified: bool


class Finding(BaseModel):
    """One check's verdict. `code` is stable and greppable (used as the audit log's
    `reason_codes` and in tests), `detail` is the human-readable why.
    """

    code: str
    outcome: GuardianOutcome
    detail: str


class GuardianVerdict(BaseModel):
    outcome: GuardianOutcome
    reason_codes: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    safe_answer: str
    policy_version: int


_BLOCK_MESSAGE = (
    "This answer was blocked before being shown. Reason code(s): {codes}. "
    "Try a narrower question, or contact an administrator if you believe this is wrong."
)
_ESCALATE_MESSAGE = (
    "This answer did not pass every safety check and has been queued for human review rather "
    "than shown as fully trustworthy. Reason code(s): {codes}."
)


class Guardian:
    """Stateless apart from the policy it was built with -- `review()` takes everything else as
    an argument, so one instance is safe to reuse across requests (mirrors `TextToSqlService`/
    `CorrectiveRagService`'s own construction pattern: expensive setup once, cheap calls after).
    """

    def __init__(self, policy: DisclosurePolicy | None = None) -> None:
        self._policy = policy or load_policy()

    def review(self, result: _Reviewable) -> GuardianVerdict:
        answer = result.answer or ""
        findings: list[Finding] = [
            *self._check_canary(answer),
            *self._check_restricted_names(answer),
            *self._check_raw_row_shape(answer),
            *self._check_role_policy(result),
            *self._check_vendor_audience(result),
            *self._check_secrets(answer),
            *self._check_pii(answer),
            *self._check_grounding(result),
        ]

        outcome: GuardianOutcome = "allow"
        for f in findings:
            if _SEVERITY[f.outcome] > _SEVERITY[outcome]:
                outcome = f.outcome
        reason_codes = [f.code for f in findings if f.outcome != "allow"]

        if outcome == "block":
            safe_answer = _BLOCK_MESSAGE.format(codes=", ".join(reason_codes))
        elif outcome == "escalate":
            safe_answer = _ESCALATE_MESSAGE.format(codes=", ".join(reason_codes))
        elif outcome == "redact":
            safe_answer = self._apply_redactions(answer, findings)
        else:
            safe_answer = answer

        return GuardianVerdict(
            outcome=outcome,
            reason_codes=reason_codes,
            findings=findings,
            safe_answer=safe_answer,
            policy_version=self._policy.version,
        )

    # -- checks, cheapest first -------------------------------------------------------------

    def _check_canary(self, answer: str) -> list[Finding]:
        prefix = self._policy.canary.prefix
        if prefix and prefix in answer:
            return [
                Finding(
                    code="canary_leak",
                    outcome="block",
                    detail=f"answer contains the canary prefix {prefix!r} -- a system prompt "
                    "or internal-only marker leaked into the output",
                )
            ]
        return []

    def _check_restricted_names(self, answer: str) -> list[Finding]:
        hits = [name for name in self._policy.restricted_names if name in answer]
        if hits:
            return [
                Finding(
                    code="restricted_name_leak",
                    outcome="block",
                    detail=f"answer names a Restricted table/view: {', '.join(hits)}",
                )
            ]
        return []

    def _check_raw_row_shape(self, answer: str) -> list[Finding]:
        if RAW_ROW_PATTERN.search(answer):
            return [
                Finding(
                    code="suspected_raw_row_dump",
                    outcome="block",
                    detail="answer contains 10+ consecutive delimited lines -- looks like a "
                    "raw row-level export rather than an aggregate summary",
                )
            ]
        return []

    def _check_role_policy(self, result: _Reviewable) -> list[Finding]:
        touched: set[DataClass] = {dc for r in result.results for dc in r.data_classes}
        findings = []
        for dc in sorted(touched):
            if not self._policy.can_view(result.role, dc):
                findings.append(
                    Finding(
                        code=f"role_policy:{dc}",
                        outcome="block",
                        detail=f"role '{result.role}' may not see '{dc}' data, but a "
                        "specialist's result touched it",
                    )
                )
        return findings

    def _check_vendor_audience(self, result: _Reviewable) -> list[Finding]:
        """Master prompt C4: a vendor-facing draft may contain only Public data plus that
        vendor's own contract terms -- never internal margins, leakage figures, risk scores, or
        any other vendor's terms. Guardian cannot tell "this vendor's own confidential terms"
        from "someone else's" by reading final text alone (ADR-006), so the Day 7 minimum is
        stricter than the letter of the spec: if the answer contains an Action draft at all, NO
        other specialist may have contributed anything beyond Public into the same answer --
        internal/confidential context has no business reaching an outbound draft's answer in the
        first place, borderline cases included.
        """
        has_action = any(r.agent == "action" for r in result.results)
        if not has_action:
            return []
        allowed = set(self._policy.vendor_facing_audience.allowed_classes)
        offending = sorted(
            {
                dc
                for r in result.results
                if r.agent != "action"
                for dc in r.data_classes
                if dc not in allowed
            }
        )
        if offending:
            return [
                Finding(
                    code="vendor_audience_violation",
                    outcome="block",
                    detail=f"answer includes an Action draft, but another specialist's data "
                    f"classes {offending} go beyond what a vendor-facing draft may contain "
                    f"({sorted(allowed)}, plus that vendor's own terms)",
                )
            ]
        return []

    def _check_secrets(self, answer: str) -> list[Finding]:
        findings = []
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(answer):
                findings.append(
                    Finding(
                        code=f"secret:{name}",
                        outcome="block",
                        detail=f"answer matches the {name} secret pattern",
                    )
                )
        return findings

    def _check_pii(self, answer: str) -> list[Finding]:
        entities = find_pii(answer)
        return [
            Finding(
                code=f"pii:{e.entity_type.lower()}",
                outcome="redact",
                detail=f"found a {e.entity_type} entity via {e.source}",
            )
            for e in entities
        ]

    def _check_grounding(self, result: _Reviewable) -> list[Finding]:
        """The Verifier's own verdict (Day 6 step 4) is Guardian's grounding check -- master
        prompt C4: "Grounding verdict from the Verifier must pass; otherwise block or answer
        with a stated gap." `Orchestrator._finalize` already finalizes an unresolved draft
        honestly-flagged (`verified=False`) rather than looping forever; Guardian routes that
        case to ESCALATE (queued for human review) rather than BLOCK (ADR-006 question 1) --
        the draft is not known-unsafe, only unconfirmed-safe.
        """
        if not result.verified:
            return [
                Finding(
                    code="unverified_grounding",
                    outcome="escalate",
                    detail="the Verifier did not pass this draft within the redraft budget; "
                    "finalized anyway (Day 6 policy) rather than shown as fully trustworthy",
                )
            ]
        return []

    # -- redaction ---------------------------------------------------------------------------

    def _apply_redactions(self, answer: str, findings: list[Finding]) -> str:
        redacted = answer
        for e in find_pii(answer):
            redacted = redacted.replace(e.text, f"[REDACTED:{e.entity_type}]")
        return redacted


__all__ = [
    "RAW_ROW_PATTERN",
    "SECRET_PATTERNS",
    "Finding",
    "Guardian",
    "GuardianOutcome",
    "GuardianVerdict",
]
