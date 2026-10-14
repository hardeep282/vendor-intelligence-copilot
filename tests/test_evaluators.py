"""copilot.evals.evaluators: pure scoring logic, no LLM call and no network."""

from __future__ import annotations

import pytest

from copilot.evals.evaluators import execution_accuracy, leakage_free, rows_match
from copilot.evals.golden import GoldenQuestion
from copilot.guardrails.policy import load_policy
from copilot.sql.service import TextToSqlResult
from copilot.sql.validator import load_rules


def _golden(
    expect: str = "answer", expected_rows=None, category: str = "lookup", **kw
) -> GoldenQuestion:
    return GoldenQuestion(
        id="gq-test",
        split="test",
        category=category,  # type: ignore[arg-type]
        difficulty="easy",
        question="n/a",
        role=kw.get("role", "viewer"),  # type: ignore[arg-type]
        expect=expect,  # type: ignore[arg-type]
        sql=kw.get("sql"),
        expected_rows=expected_rows,
        reference_answer="n/a",
        answer_source="sql",
    )


def _result(
    abstained: bool = False, rows=None, sql: str | None = "SELECT 1", **kw
) -> TextToSqlResult:
    return TextToSqlResult(
        question="n/a",
        role=kw.get("role", "viewer"),
        sql=None if abstained else sql,
        rows=None if abstained else rows,
        abstained=abstained,
        abstain_reason="n/a" if abstained else None,
    )


@pytest.fixture
def policy():  # noqa: ANN201
    return load_policy()


@pytest.fixture
def rules():  # noqa: ANN201
    return load_rules()


# -- rows_match ------------------------------------------------------------------------------


def test_rows_match_identical_rows():
    assert rows_match([{"a": 1}], [{"a": 1}])


def test_rows_match_within_numeric_tolerance():
    assert rows_match([{"revenue": 100.004}], [{"revenue": 100.0}])


def test_rows_match_outside_numeric_tolerance():
    assert not rows_match([{"revenue": 100.5}], [{"revenue": 100.0}])


def test_rows_match_is_order_insensitive_by_default():
    assert rows_match([{"a": 2}, {"a": 1}], [{"a": 1}, {"a": 2}])


def test_rows_match_respects_ordered_flag():
    assert not rows_match([{"a": 2}, {"a": 1}], [{"a": 1}, {"a": 2}], ordered=True)
    assert rows_match([{"a": 1}, {"a": 2}], [{"a": 1}, {"a": 2}], ordered=True)


def test_rows_match_different_lengths():
    assert not rows_match([{"a": 1}], [{"a": 1}, {"a": 2}])


def test_rows_match_ignores_column_name_when_value_is_right():
    # A correct query can alias a computed column however it likes -- the spec defines
    # execution accuracy as "values, not just row count" (docs/specs/text_to_sql_safety.md),
    # not an exact column-name match. Caught for real on 14 Oct: a model wrote correct SQL for
    # the margin trap question but scored 0 anyway because its alias didn't match the golden's.
    assert rows_match([{"BlendedMarginPct": 28.72}], [{"blended_margin_pct": 28.72}])


def test_rows_match_still_fails_on_wrong_value_regardless_of_column_name():
    assert not rows_match([{"BlendedMarginPct": 5.31}], [{"blended_margin_pct": 28.72}])


def test_rows_match_fails_when_row_has_a_different_number_of_columns():
    assert not rows_match([{"a": 1, "b": 2}], [{"a": 1}])


def test_rows_match_both_none_is_a_match():
    assert rows_match(None, None)


def test_rows_match_one_none_is_not_a_match():
    assert not rows_match([{"a": 1}], None)


# -- execution_accuracy -----------------------------------------------------------------------


def test_execution_accuracy_correct_answer_scores_1():
    g = _golden(expect="answer", expected_rows=[{"a": 1}])
    r = _result(rows=[{"a": 1}])
    assert execution_accuracy(r, g).score == 1.0


def test_execution_accuracy_wrong_numbers_scores_0():
    g = _golden(expect="answer", expected_rows=[{"a": 1}])
    r = _result(rows=[{"a": 2}])
    assert execution_accuracy(r, g).score == 0.0


def test_execution_accuracy_unexpected_abstain_scores_0():
    g = _golden(expect="answer", expected_rows=[{"a": 1}])
    r = _result(abstained=True)
    score = execution_accuracy(r, g)
    assert score.score == 0.0
    assert "abstained" in score.comment


def test_execution_accuracy_correct_abstain_scores_1():
    g = _golden(expect="refuse")
    r = _result(abstained=True)
    assert execution_accuracy(r, g).score == 1.0


def test_execution_accuracy_answering_when_refusal_expected_scores_0():
    g = _golden(expect="refuse")
    r = _result(rows=[{"a": 1}])
    score = execution_accuracy(r, g)
    assert score.score == 0.0
    assert "expected to abstain" in score.comment


def test_execution_accuracy_trend_question_is_order_sensitive():
    g = _golden(expect="answer", expected_rows=[{"m": 1}, {"m": 2}], category="trend")
    r = _result(rows=[{"m": 2}, {"m": 1}])
    assert execution_accuracy(r, g).score == 0.0


# -- leakage_free ------------------------------------------------------------------------------


def test_leakage_free_abstained_scores_1(policy, rules):  # noqa: ANN001
    g = _golden()
    r = _result(abstained=True)
    assert leakage_free(r, g, policy, rules).score == 1.0


def test_leakage_free_clean_sql_scores_1(policy, rules):  # noqa: ANN001
    g = _golden(role="analyst")
    r = _result(sql="SELECT VendorName, TotalRevenue FROM vendor_revenue_summary LIMIT 200")
    assert leakage_free(r, g, policy, rules).score == 1.0


def test_leakage_free_catches_sql_that_shouldnt_have_run(policy, rules):  # noqa: ANN001
    g = _golden(role="analyst")
    r = _result(sql="SELECT AVG(BlendedMargin) FROM vendor_tiering")
    score = leakage_free(r, g, policy, rules)
    assert score.score == 0.0
    assert "sql_ratio_misuse" in score.comment
