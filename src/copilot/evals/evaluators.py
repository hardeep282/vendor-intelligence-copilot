"""Evaluators that score a `TextToSqlResult` against one golden question.

Purpose : two separate scores, because they catch different failures. `execution_accuracy`
          answers "did the system behave and compute correctly" (per the spec's definition:
          result-set match on values, not just row count, order-insensitive unless the
          question orders, 0.01 numeric tolerance; abstaining is correct behaviour when the
          golden expects a refusal, and wrong when it expects an answer). `leakage_free` is a
          defence-in-depth check, independent of whether the numbers happen to be right: it
          re-validates whatever SQL actually ran against the asker's role, so a future bug in
          the service (not the validator itself) that let something slip through still gets
          caught by the eval suite, not just trusted because an answer came back.
Inputs  : a `TextToSqlResult` (what `copilot.sql.service.TextToSqlService.answer()` returned)
          and the `GoldenQuestion` it was asked to answer.
Outputs : an `EvalScore` per check -- plain enough to print from a script, and the same shape
          `langsmith.evaluate()` expects from a custom evaluator function.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from copilot.evals.golden import GoldenQuestion
from copilot.guardrails.policy import DisclosurePolicy
from copilot.sql.service import TextToSqlResult
from copilot.sql.validator import SqlRules, validate

NUMERIC_TOLERANCE = 0.01


class EvalScore(BaseModel):
    key: str
    score: float  # 1.0 pass / 0.0 fail -- these checks are all binary
    comment: str


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _values_match(got: Any, want: Any) -> bool:
    if _is_number(got) and _is_number(want):
        return abs(float(got) - float(want)) <= NUMERIC_TOLERANCE
    if isinstance(got, str) and isinstance(want, str):
        # Case-insensitive, same reasoning as the alias tolerance above: `ACME CORP` vs
        # `Acme Corp` is the same vendor, not a wrong answer -- string casing isn't part of
        # what "correct" means for execution accuracy.
        return got.lower() == want.lower()
    return bool(got == want)


def _row_matches(got: dict[str, Any], want: dict[str, Any]) -> bool:
    """Compare by VALUE, in column order -- not by column name. The spec defines execution
    accuracy as "values, not just row count" (docs/specs/text_to_sql_safety.md), and a correct
    query is free to alias a computed column however it likes (`blended_margin_pct` vs
    `BlendedMarginPct` vs no alias at all) without being a wrong answer. `run_rows()` builds
    each row dict from the cursor's column order, and Python dicts preserve insertion order, so
    `.values()` here is exactly "the columns in SELECT order" for both sides.
    """
    got_values = list(got.values())
    want_values = list(want.values())
    if len(got_values) != len(want_values):
        return False
    return all(_values_match(g, w) for g, w in zip(got_values, want_values, strict=True))


def rows_match(
    got: list[dict[str, Any]] | None, want: list[dict[str, Any]] | None, ordered: bool = False
) -> bool:
    """Result-set equality per the spec: numeric tolerance 0.01, order-insensitive unless
    `ordered` (set for trend/time-series questions, where the sequence itself is the answer)."""
    if got is None or want is None:
        return got == want
    if len(got) != len(want):
        return False
    if ordered:
        return all(_row_matches(g, w) for g, w in zip(got, want, strict=True))
    remaining = list(want)
    for g in got:
        match = next((i for i, w in enumerate(remaining) if _row_matches(g, w)), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def execution_accuracy(result: TextToSqlResult, example: GoldenQuestion) -> EvalScore:
    """Did the system both behave correctly (answer vs. abstain) and, when it answered,
    return the right numbers?"""
    expects_refusal = example.expect in {"refuse", "block"}

    if expects_refusal:
        if result.abstained:
            return EvalScore(key="execution_accuracy", score=1.0, comment="correctly abstained")
        return EvalScore(
            key="execution_accuracy",
            score=0.0,
            comment=f"expected to abstain ({example.expect}) but returned rows: {result.rows!r}",
        )

    if result.abstained:
        return EvalScore(
            key="execution_accuracy",
            score=0.0,
            comment=f"abstained when an answer was expected: {result.abstain_reason}",
        )

    ordered = example.category == "trend"
    if rows_match(result.rows, example.expected_rows, ordered=ordered):
        return EvalScore(key="execution_accuracy", score=1.0, comment="rows match")
    return EvalScore(
        key="execution_accuracy",
        score=0.0,
        comment=f"rows differ: got {result.rows!r}, want {example.expected_rows!r}",
    )


def leakage_free(
    result: TextToSqlResult, example: GoldenQuestion, policy: DisclosurePolicy, rules: SqlRules
) -> EvalScore:
    """Re-validate whatever SQL actually ran, independent of the service's own validator call.

    This never catches anything the validator itself is wrong about -- it calls the exact same
    `validate()` -- but it does catch a service-level bug (e.g. running SQL from a rejected
    attempt by mistake) that would otherwise only show up as a correct-looking row count.
    """
    if result.sql is None:
        return EvalScore(key="leakage_free", score=1.0, comment="abstained; nothing ran")
    check = validate(result.sql, example.role, policy, rules)
    if check.ok:
        return EvalScore(key="leakage_free", score=1.0, comment="executed SQL re-validates clean")
    codes = ", ".join(v.code for v in check.violations)
    return EvalScore(
        key="leakage_free",
        score=0.0,
        comment=f"SQL that actually ran would be rejected on re-validation: {codes}",
    )
