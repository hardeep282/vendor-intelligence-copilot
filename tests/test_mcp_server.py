"""Tests for the Vendor Analytics MCP server (Day 9 step 4, copilot.mcp.server).

Calls the tool functions directly (the same plain Python callables `@mcp.tool()` registers --
real stdio-protocol wiring is covered separately by an MCP Inspector run, see docs/BUILD_LOG.md)
against a synthetic in-memory DuckDB fixture, same "schema, not licensed data" convention
tests/test_sql_validator.py and tests/test_generate_sql_pairs.py already use. The module-level
`@lru_cache` singletons are cleared before and after every test so one test's monkeypatched
connection can never leak into another.
"""

from __future__ import annotations

import duckdb
import pytest

import copilot.mcp.server as mcp_server
from copilot.llm.client import LLMClient
from copilot.settings import get_settings
from copilot.sql.service import TextToSqlService
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _clear_lru_caches() -> None:
    # Some tests monkeypatch a cached getter to a plain lambda for the duration of the test;
    # monkeypatch restores the original (real lru_cache-wrapped) object afterwards, but at the
    # moment *this* fixture's own post-yield code runs, that restore hasn't happened yet --
    # hence the hasattr guard rather than a bare .cache_clear() call.
    for name in ("_get_connection", "_get_sql_service", "_get_guardian"):
        getter = getattr(mcp_server, name)
        if hasattr(getter, "cache_clear"):
            getter.cache_clear()
    # get_settings() is ALSO @lru_cache'd (src/copilot/settings.py) -- on a machine with a real
    # ANTHROPIC_API_KEY set (in the OS environment or a local .env file), whichever test in the
    # whole run calls get_settings() first caches a Settings object with that real key baked in,
    # for the rest of the process. test_ask_vendor_question_reports_a_clean_error_with_no_api_key
    # below then monkeypatches *os.environ*, which does nothing to that already-cached object --
    # LLMClient() still sees the real key and the test sees `answered: True` where it expected a
    # clean "no key" error. Invisible on a machine with no key configured anywhere (this is why
    # it passed throughout Day 9); real once a real key exists. Same fix already applied in
    # test_api.py, test_api_ask.py and test_api_dependencies.py -- this file just didn't have it
    # yet, not a new gap.
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear_lru_caches()
    yield
    _clear_lru_caches()


@pytest.fixture
def con(monkeypatch: pytest.MonkeyPatch) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE vendor_revenue_summary (VendorName VARCHAR, TotalRevenue DOUBLE, "
        "BlendedMarginPct DOUBLE, NumberOfSKUs INT, MeetsMinK BOOLEAN)"
    )
    c.execute(
        "INSERT INTO vendor_revenue_summary VALUES "
        "('ACME BEVERAGES', 100000.0, 20.0, 12, true), "
        "('TINY VENDOR CO', 500.0, 10.0, 2, false)"
    )
    c.execute(
        "CREATE TABLE vendor_tiering (VendorName VARCHAR, RevenueTier VARCHAR, TierLabel VARCHAR)"
    )
    c.execute("INSERT INTO vendor_tiering VALUES ('ACME BEVERAGES', 'A', 'Core')")
    c.execute("CREATE TABLE vendor_pareto (VendorName VARCHAR, ParetoBand VARCHAR)")
    c.execute("INSERT INTO vendor_pareto VALUES ('ACME BEVERAGES', 'Top 80%')")
    c.execute("CREATE TABLE portfolio_health_mix (HealthStatus VARCHAR, SKUs INT, SharePct DOUBLE)")
    c.execute("INSERT INTO portfolio_health_mix VALUES ('Healthy', 12, 100.0)")

    monkeypatch.setattr(mcp_server, "_get_connection", lambda: c)
    return c


# -- vendor_metrics ---------------------------------------------------------------------------


def test_vendor_metrics_returns_joined_headline_fields(con) -> None:
    result = mcp_server.vendor_metrics("ACME BEVERAGES")
    assert result["found"] is True
    assert result["total_revenue"] == 100000.0
    assert result["revenue_tier"] == "A"
    assert result["pareto_band"] == "Top 80%"


def test_vendor_metrics_withholds_a_vendor_below_min_k(con) -> None:
    # TINY VENDOR CO has MeetsMinK = false -- must come back as not-found, not as real numbers.
    result = mcp_server.vendor_metrics("TINY VENDOR CO")
    assert result["found"] is False


def test_vendor_metrics_handles_an_unknown_vendor_without_raising(con) -> None:
    result = mcp_server.vendor_metrics("NO SUCH VENDOR")
    assert result["found"] is False
    assert "NO SUCH VENDOR" in result["message"]


# -- portfolio_summary ------------------------------------------------------------------------


def test_portfolio_summary_aggregates_across_every_vendor(con) -> None:
    result = mcp_server.portfolio_summary()
    assert result["vendor_count"] == 2  # both rows, including the sub-min-k one -- a portfolio
    # total legitimately includes it; only vendor-level lookups withhold it.
    assert result["total_revenue"] == 100500.0
    assert result["pareto_bands"] == {"Top 80%": 1}
    assert result["sku_health_mix"] == [
        {"health_status": "Healthy", "skus": 12, "share_pct": 100.0}
    ]


# -- ask_vendor_question -----------------------------------------------------------------------


def test_ask_vendor_question_reports_a_clean_error_with_no_api_key(con, monkeypatch) -> None:
    # setenv("", not delenv: Settings (src/copilot/settings.py) reads a local .env file as a
    # fallback source, and pydantic-settings' own precedence is os.environ > .env file. delenv
    # only removes the OS variable -- on any machine that has a real ANTHROPIC_API_KEY in a
    # .env file (every machine that's ever run the real LLM path locally, almost certainly
    # including whoever runs this test outside a from-scratch CI container), Settings falls
    # straight through to that file's real key regardless of get_settings.cache_clear() above.
    # Reproduced and confirmed directly before writing this fix: delenv + cache_clear alone
    # still returned a real key with a .env file present; setenv("", ...) + cache_clear did not,
    # because an empty string in os.environ outranks the .env file's value. An empty string is
    # the same falsy-key case `scripts/run_eval_gate.py` already hardens against, not a new
    # pattern invented for this test.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    result = mcp_server.ask_vendor_question("What is the total revenue?")
    assert result["answered"] is False
    assert "error" in result
    assert "API key" in result["error"]


def test_ask_vendor_question_runs_validated_sql_and_passes_guardian(con, monkeypatch) -> None:
    fake = FakeMessagesResource(
        [
            structured_response(
                {
                    "sql": "SELECT VendorName, TotalRevenue FROM vendor_revenue_summary "
                    "WHERE VendorName = 'ACME BEVERAGES'",
                    "assumptions": [],
                }
            )
        ]
    )
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    fake_service = TextToSqlService(llm, con=con)
    monkeypatch.setattr(mcp_server, "_get_sql_service", lambda: fake_service)

    result = mcp_server.ask_vendor_question("What is Acme Beverages's total revenue?")

    assert result["answered"] is True
    assert result["guardian_outcome"] == "allow"
    assert result["row_count"] == 1
    assert result["answer"] == "For ACME BEVERAGES: TotalRevenue 100,000.0"


def test_format_rows_avoids_the_presidio_location_false_positive() -> None:
    # Regression test for the exact finding documented in _format_rows's own docstring: a
    # "Column: value" rendering directly after an all-caps multi-word vendor name made
    # Presidio's NER flag the vendor name itself as a false-positive LOCATION entity.
    from copilot.guardrails.pii import find_pii

    rendered = mcp_server._format_rows([{"VendorName": "ACME BEVERAGES", "TotalRevenue": 100000.0}])
    assert rendered == "For ACME BEVERAGES: TotalRevenue 100,000.0"
    assert find_pii(rendered) == []


def test_format_rows_handles_a_single_column_row_with_no_subject() -> None:
    assert mcp_server._format_rows([{"vendors": 126}]) == "vendors 126"


def test_format_rows_handles_no_rows() -> None:
    assert mcp_server._format_rows([]) == "(query returned no rows)"


def test_ask_vendor_question_reports_abstention_without_calling_guardian(con, monkeypatch) -> None:
    fake = FakeMessagesResource(
        [structured_response({"sql": None, "abstain_reason": "out of scope"})]
    )
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = fake  # type: ignore[attr-defined]
    fake_service = TextToSqlService(llm, con=con)
    monkeypatch.setattr(mcp_server, "_get_sql_service", lambda: fake_service)

    result = mcp_server.ask_vendor_question("What's the weather like?")

    assert result["answered"] is False
    assert result["abstain_reason"] == "out of scope"
    assert "guardian_outcome" not in result
