"""TextToSqlService: schema linking, validator wiring and the self-correction loop, all
against fakes (no network call, no API key -- same pattern as test_insight_service.py).

The disclosure policy and SQL rules used here are the REAL ones (policies/disclosure.yaml,
policies/sql_rules.yaml), since those are what the validator actually enforces in prod; only
the DuckDB data and the LLM responses are faked.
"""

from __future__ import annotations

import duckdb
import pytest

from copilot.guardrails.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.sql.service import TextToSqlResult, TextToSqlService
from copilot.sql.validator import load_rules
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE vendor_tiering (VendorName VARCHAR, TotalProfit DOUBLE, "
        "TotalRevenue DOUBLE, BlendedMargin DOUBLE)"
    )
    c.execute("INSERT INTO vendor_tiering VALUES ('BIG CO', 285000.0, 1000000.0, 28.5)")
    return c


@pytest.fixture
def policy():  # noqa: ANN201
    return load_policy()


@pytest.fixture
def rules():  # noqa: ANN201
    return load_rules()


def _service(con, policy, rules, fake: FakeMessagesResource) -> TextToSqlService:  # noqa: ANN001
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    return TextToSqlService(llm, con=con, policy=policy, rules=rules)


def test_valid_sql_on_first_attempt_returns_real_rows(con, policy, rules) -> None:  # noqa: ANN001
    fake = FakeMessagesResource(
        [
            structured_response(
                {
                    "sql": "SELECT VendorName, TotalRevenue FROM vendor_tiering "
                    "WHERE VendorName = 'BIG CO'",
                    "assumptions": [],
                }
            )
        ]
    )
    result = _service(con, policy, rules, fake).answer("What is BIG CO's revenue?", role="viewer")

    assert isinstance(result, TextToSqlResult)
    assert not result.abstained
    assert result.rows == [{"VendorName": "BIG CO", "TotalRevenue": 1000000.0}]
    assert result.self_corrections == 0
    assert len(fake.calls) == 1


def test_validator_rejection_is_fed_back_and_self_corrected(con, policy, rules) -> None:  # noqa: ANN001
    fake = FakeMessagesResource(
        [
            structured_response(
                {"sql": "SELECT AVG(BlendedMargin) FROM vendor_tiering", "assumptions": []}
            ),
            structured_response(
                {
                    "sql": "SELECT SUM(TotalProfit) / SUM(TotalRevenue) AS margin "
                    "FROM vendor_tiering",
                    "assumptions": ["treated the portfolio margin as a ratio of sums"],
                }
            ),
        ]
    )
    result = _service(con, policy, rules, fake).answer(
        "What is the portfolio's blended margin?", role="analyst"
    )

    assert not result.abstained
    assert result.rows == [{"margin": 0.28}]  # run_rows rounds floats to 2 dp for comparison
    assert result.self_corrections == 1
    assert len(fake.calls) == 2
    # The rejected SQL and the exact violation code must have been fed back as context.
    second_call_messages = fake.calls[1]["messages"]
    assert any("AVG(BlendedMargin)" in str(m["content"]) for m in second_call_messages)
    assert any("sql_ratio_misuse" in str(m["content"]) for m in second_call_messages)


def test_model_abstaining_directly_never_touches_the_validator(con, policy, rules) -> None:  # noqa: ANN001
    fake = FakeMessagesResource(
        [
            structured_response(
                {
                    "sql": None,
                    "assumptions": [],
                    "abstain_reason": "the data covers 2024 only; 2025 is not available",
                }
            )
        ]
    )
    result = _service(con, policy, rules, fake).answer(
        "What was revenue in Q1 2025?", role="viewer"
    )

    assert result.abstained
    assert result.sql is None
    assert result.rows is None
    assert "2024" in (result.abstain_reason or "")
    assert len(fake.calls) == 1


def test_exhausting_self_corrections_abstains_with_the_last_violation(con, policy, rules) -> None:  # noqa: ANN001
    bad = structured_response({"sql": "SELECT * FROM system_users", "assumptions": []})
    fake = FakeMessagesResource([bad, bad, bad])  # 1 attempt + MAX_SELF_CORRECTIONS retries = 3

    result = _service(con, policy, rules, fake).answer("Show me everything", role="analyst")

    assert result.abstained
    assert result.self_corrections == 2
    assert "sql_table_not_allowed" in (result.abstain_reason or "")
    assert len(fake.calls) == 3
