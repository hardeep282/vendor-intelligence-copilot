"""copilot.insights.service: grounding (DuckDB) and the LLM call, both against fakes.

No network call and no API key is used here (see tests/test_llm_client.py's note): the LLM
side is the same FakeMessagesResource used there, and the data side is an in-memory DuckDB
database built from a handful of rows, not the real snapshot.
"""

from __future__ import annotations

import duckdb
import pytest

from copilot.guardrails.policy import load_policy
from copilot.insights.service import (
    InsightService,
    VendorInsight,
    VendorNotFoundError,
    gather_vendor_data,
)
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE vendor_revenue_summary (VendorName VARCHAR, TotalRevenue DOUBLE, "
        "BlendedMarginPct DOUBLE, MeetsMinK BOOLEAN)"
    )
    c.execute(
        "INSERT INTO vendor_revenue_summary VALUES "
        "('BIG CO', 1000000.0, 28.5, true), "
        "('TINY CO', 5000.0, 10.0, false)"
    )
    c.execute(
        "CREATE TABLE vendor_tiering (VendorName VARCHAR, SKUCount INTEGER, "
        "TierLabel VARCHAR, MeetsMinK BOOLEAN)"
    )
    c.execute(
        "INSERT INTO vendor_tiering VALUES "
        "('BIG CO', 400, 'Tier 1 — Premium', true), "
        "('TINY CO', 2, 'Tier 4 — Long Tail', false)"
    )
    c.execute(
        "CREATE TABLE vendor_profit_leakage (VendorName VARCHAR, TotalLeakageAmount DOUBLE, "
        "MeetsMinK BOOLEAN)"
    )
    c.execute(
        "INSERT INTO vendor_profit_leakage VALUES "
        "('BIG CO', 50000.0, true), "
        "('TINY CO', 500.0, false)"
    )
    return c


@pytest.fixture
def policy():  # noqa: ANN201
    return load_policy()


def test_gather_vendor_data_full_for_role_without_k_gate(con, policy) -> None:  # noqa: ANN001
    data = gather_vendor_data(con, "BIG CO", policy, role="analyst")
    assert data["vendor_revenue_summary"]["TotalRevenue"] == 1000000.0
    assert "withheld" not in data["vendor_revenue_summary"]


def test_gather_vendor_data_withholds_below_k_for_gated_role(con, policy) -> None:  # noqa: ANN001
    data = gather_vendor_data(con, "TINY CO", policy, role="viewer")
    assert data["vendor_revenue_summary"] == {"withheld": "below minimum aggregation threshold"}
    assert data["vendor_tiering"] == {"withheld": "below minimum aggregation threshold"}


def test_gather_vendor_data_shows_below_k_to_ungated_role(con, policy) -> None:  # noqa: ANN001
    data = gather_vendor_data(con, "TINY CO", policy, role="analyst")
    assert data["vendor_revenue_summary"]["TotalRevenue"] == 5000.0


def test_gather_vendor_data_unknown_vendor_raises(con, policy) -> None:  # noqa: ANN001
    with pytest.raises(VendorNotFoundError):
        gather_vendor_data(con, "NO SUCH VENDOR", policy, role="viewer")


def test_vendor_insight_calls_llm_with_grounded_data_and_returns_typed_result(
    con,
    policy,  # noqa: ANN001
) -> None:
    llm = LLMClient(api_key="sk-test-not-real")
    fake = FakeMessagesResource(
        [
            structured_response(
                {
                    "vendor_name": "BIG CO",
                    "headline": "Strong margin, Tier 1 vendor",
                    "narrative": "BIG CO generated $1,000,000.0 in revenue at a 28.5% "
                    "blended margin, with $50,000.0 in total leakage.",
                    "key_metrics_cited": ["TotalRevenue", "BlendedMarginPct", "TotalLeakageAmount"],
                    "risk_flags": [],
                }
            )
        ]
    )
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = InsightService(llm, con=con, policy=policy)

    insight, metrics = service.vendor_insight("BIG CO", role="viewer")

    assert isinstance(insight, VendorInsight)
    assert insight.vendor_name == "BIG CO"
    assert insight.key_metrics_cited == ["TotalRevenue", "BlendedMarginPct", "TotalLeakageAmount"]
    assert metrics.cost_usd > 0

    sent = fake.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["output_config"] == {"effort": "medium"}
    assert "BIG CO" in sent["messages"][0]["content"]
    assert "1000000.0" in sent["messages"][0]["content"]


def test_vendor_insight_unknown_vendor_never_calls_llm(con, policy) -> None:  # noqa: ANN001
    llm = LLMClient(api_key="sk-test-not-real")
    fake = FakeMessagesResource([])
    llm._client.messages = fake  # type: ignore[attr-defined]
    service = InsightService(llm, con=con, policy=policy)

    with pytest.raises(VendorNotFoundError):
        service.vendor_insight("NO SUCH VENDOR", role="viewer")
    assert fake.calls == []
