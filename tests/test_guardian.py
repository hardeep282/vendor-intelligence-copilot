"""Tests for the Guardian (Day 7 steps 1 and 3): every check, worst-wins severity, and the
safe_answer each outcome produces. Builds `OrchestratorResult` directly rather than running the
full graph -- `tests/test_orchestrator.py` (step 4, topology) covers the wiring; this file
covers the Guardian's own decision logic in isolation, same split `test_sql_validator.py` uses
for the validator vs. `test_text_to_sql_service.py` for the service around it.
"""

from __future__ import annotations

from copilot.agents.contracts import AgentResult
from copilot.agents.orchestrator import OrchestratorResult
from copilot.guardrails.canary import canary_line, canary_token
from copilot.guardrails.guardian import Guardian


def _result(
    role: str = "viewer",
    answer: str = "Top vendor by revenue is DIAGEO at $45.2M.",
    results: list[AgentResult] | None = None,
    verified: bool = True,
) -> OrchestratorResult:
    return OrchestratorResult(
        question="who is the top vendor?",
        role=role,  # type: ignore[arg-type]
        results=results or [],
        answer=answer,
        verified=verified,
    )


def _ar(agent: str, data_classes: list[str]) -> AgentResult:
    return AgentResult(
        task_id="t1",
        agent=agent,  # type: ignore[arg-type]
        status="ok",
        findings="x",
        data_classes=data_classes,  # type: ignore[arg-type]
    )


def test_clean_answer_allows() -> None:
    verdict = Guardian().review(_result(results=[_ar("data_analyst", ["internal"])]))
    assert verdict.outcome == "allow"
    assert verdict.reason_codes == []
    assert verdict.safe_answer == "Top vendor by revenue is DIAGEO at $45.2M."


def test_canary_leak_blocks() -> None:
    answer = f"Here is the answer. {canary_token('data_analyst')}"
    verdict = Guardian().review(_result(answer=answer))
    assert verdict.outcome == "block"
    assert "canary_leak" in verdict.reason_codes
    assert canary_token("data_analyst") not in verdict.safe_answer


def test_canary_line_contains_its_own_token() -> None:
    # The exact line planted in a system prompt must itself trip the check -- proves the two
    # halves (canary.py's line, guardian.py's scan) actually agree on the token shape.
    line = canary_line("knowledge")
    verdict = Guardian().review(_result(answer=f"irrelevant preamble {line}"))
    assert verdict.outcome == "block"


def test_restricted_name_blocks() -> None:
    verdict = Guardian().review(_result(answer="Computed from vw_PortfolioHealth directly."))
    assert verdict.outcome == "block"
    assert "restricted_name_leak" in verdict.reason_codes


def test_raw_row_dump_blocks() -> None:
    rows = "\n".join(f"SKU{i}|Vendor{i}|{i*10}" for i in range(15))
    verdict = Guardian().review(_result(answer=f"Here are the rows:\n{rows}"))
    assert verdict.outcome == "block"
    assert "suspected_raw_row_dump" in verdict.reason_codes


def test_short_markdown_table_does_not_block() -> None:
    # A handful of summary rows is normal output, not a raw dump -- must not false-positive.
    table = "\n".join(f"Vendor{i}|${i*1000}|Tier{i % 3}" for i in range(4))
    verdict = Guardian().review(_result(answer=f"Summary:\n{table}"))
    assert verdict.outcome == "allow"


def test_role_cannot_view_data_class_blocks() -> None:
    verdict = Guardian().review(
        _result(role="viewer", results=[_ar("data_analyst", ["confidential"])])
    )
    assert verdict.outcome == "block"
    assert "role_policy:confidential" in verdict.reason_codes


def test_role_can_view_own_classes_allows() -> None:
    verdict = Guardian().review(
        _result(role="analyst", results=[_ar("data_analyst", ["confidential"])])
    )
    assert verdict.outcome == "allow"


def test_vendor_audience_violation_blocks_when_internal_data_feeds_a_draft() -> None:
    verdict = Guardian().review(
        _result(
            role="approver",
            results=[
                _ar("forecasting_risk", ["internal"]),
                _ar("action", ["confidential"]),
            ],
        )
    )
    assert verdict.outcome == "block"
    assert "vendor_audience_violation" in verdict.reason_codes


def test_action_alone_with_public_only_does_not_trip_audience_check() -> None:
    verdict = Guardian().review(
        _result(role="approver", results=[_ar("action", ["confidential"])])
    )
    # Only the Action agent's own confidential (its target vendor's terms) touched the
    # answer -- no OTHER specialist contributed internal/confidential, so the audience check
    # does not fire. (Role policy for the approver still allows confidential.)
    assert "vendor_audience_violation" not in verdict.reason_codes


def test_no_action_agent_never_trips_audience_check() -> None:
    verdict = Guardian().review(
        _result(role="analyst", results=[_ar("data_analyst", ["confidential"])])
    )
    assert "vendor_audience_violation" not in verdict.reason_codes


def test_secret_pattern_blocks() -> None:
    verdict = Guardian().review(_result(answer="Here is a key: sk-ant-abcdefghijklmnopqrstuvwx"))
    assert verdict.outcome == "block"
    assert "secret:anthropic_api_key" in verdict.reason_codes


def test_pii_email_redacts_not_blocks() -> None:
    verdict = Guardian().review(_result(answer="Reach the buyer at jane.doe@example.com."))
    assert verdict.outcome == "redact"
    assert "jane.doe@example.com" not in verdict.safe_answer
    assert "[REDACTED:EMAIL_ADDRESS]" in verdict.safe_answer


def test_unverified_draft_escalates() -> None:
    verdict = Guardian().review(_result(verified=False))
    assert verdict.outcome == "escalate"
    assert "unverified_grounding" in verdict.reason_codes


def test_block_outranks_redact_and_escalate() -> None:
    # A PII hit (redact) AND an unverified draft (escalate) AND a canary leak (block) all in
    # one answer -- block must win, and every finding is still recorded.
    answer = (
        f"Contact buyer@example.com. {canary_token('action')}"
    )
    verdict = Guardian().review(_result(answer=answer, verified=False))
    assert verdict.outcome == "block"
    assert {"canary_leak", "pii:email_address", "unverified_grounding"}.issubset(
        set(verdict.reason_codes)
    )


def test_safe_answer_never_echoes_reason_for_block_or_escalate_message_only_codes() -> None:
    verdict = Guardian().review(_result(answer="Computed from vw_PortfolioHealth."))
    assert "blocked" in verdict.safe_answer.lower()
    assert "restricted_name_leak" in verdict.safe_answer


def test_policy_version_recorded() -> None:
    verdict = Guardian().review(_result())
    assert verdict.policy_version == 1
