"""copilot.evals.effort_lab: against fakes, no network call and no API key.

The loop order inside run_effort_lab is effort -> question -> repeat, so the fake responses
below are queued in exactly that order.
"""

from __future__ import annotations

import duckdb
import pytest

from copilot.evals.effort_lab import run_effort_lab
from copilot.evals.golden import GoldenQuestion
from copilot.guardrails.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import load_rules
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE vendor_tiering (VendorName VARCHAR, TotalRevenue DOUBLE)")
    c.execute("INSERT INTO vendor_tiering VALUES ('BIG CO', 1000000.0)")
    return c


@pytest.fixture
def policy():  # noqa: ANN201
    return load_policy()


@pytest.fixture
def rules():  # noqa: ANN201
    return load_rules()


def _question(id_: str) -> GoldenQuestion:
    return GoldenQuestion(
        id=id_,
        split="dev",
        category="lookup",
        difficulty="easy",
        question="What is BIG CO's revenue?",
        role="viewer",
        expect="answer",
        sql="SELECT VendorName, TotalRevenue FROM vendor_tiering WHERE VendorName = 'BIG CO'",
        expected_rows=[{"VendorName": "BIG CO", "TotalRevenue": 1000000.0}],
        reference_answer="n/a",
        answer_source="sql",
    )


def _correct_sql_response() -> tuple:  # type: ignore[type-arg]
    return structured_response(
        {
            "sql": "SELECT VendorName, TotalRevenue FROM vendor_tiering "
            "WHERE VendorName = 'BIG CO'",
            "assumptions": [],
        }
    )


def test_sweeps_every_effort_level_and_scores_each_run(con, policy, rules) -> None:  # noqa: ANN001
    questions = [_question("gq-a")]
    fake = FakeMessagesResource([_correct_sql_response(), _correct_sql_response()])
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = TextToSqlService(llm, con=con, policy=policy, rules=rules)

    report = run_effort_lab(service, questions, policy, rules, efforts=("low", "high"))

    assert [s.effort for s in report.by_effort] == ["low", "high"]
    assert all(s.runs == 1 for s in report.by_effort)
    assert all(s.execution_accuracy_rate == 1.0 for s in report.by_effort)
    assert all(s.leakage_free_rate == 1.0 for s in report.by_effort)
    assert all(s.sql_diversity is None for s in report.by_effort)  # repeats defaults to 1

    sent_efforts = [c["output_config"]["effort"] for c in fake.calls]
    assert sent_efforts == ["low", "high"]


def test_diversity_is_none_when_repeats_is_1(con, policy, rules) -> None:  # noqa: ANN001
    questions = [_question("gq-a")]
    fake = FakeMessagesResource([_correct_sql_response()])
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = TextToSqlService(llm, con=con, policy=policy, rules=rules)

    report = run_effort_lab(service, questions, policy, rules, efforts=("low",), repeats=1)
    assert report.by_effort[0].sql_diversity is None


def test_diversity_measures_fraction_of_distinct_sql_across_repeats(con, policy, rules) -> None:  # noqa: ANN001
    questions = [_question("gq-a")]
    same = _correct_sql_response()
    different = structured_response(
        {
            "sql": "SELECT TotalRevenue FROM vendor_tiering WHERE VendorName = 'BIG CO'",
            "assumptions": [],
        }
    )
    fake = FakeMessagesResource([same, same, different])
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = TextToSqlService(llm, con=con, policy=policy, rules=rules)

    report = run_effort_lab(service, questions, policy, rules, efforts=("low",), repeats=3)

    # 2 distinct SQL strings out of 3 repeats for this one question.
    assert report.by_effort[0].sql_diversity == pytest.approx(2 / 3)
    assert report.by_effort[0].runs == 3


def test_records_carry_question_effort_and_repeat_index(con, policy, rules) -> None:  # noqa: ANN001
    questions = [_question("gq-a")]
    fake = FakeMessagesResource([_correct_sql_response(), _correct_sql_response()])
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = TextToSqlService(llm, con=con, policy=policy, rules=rules)

    report = run_effort_lab(service, questions, policy, rules, efforts=("low",), repeats=2)

    assert [r.repeat for r in report.records] == [0, 1]
    assert all(r.question_id == "gq-a" and r.effort == "low" for r in report.records)
