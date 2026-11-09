"""Vendor Analytics MCP server (Day 9 step 4, B7's companion -- "never cut" per the sprint
brief's own cut-first list).

Purpose : expose this project's read-only analytics as MCP tools, so any MCP host (Claude
          Desktop, the MCP Inspector, another agent) can query vendor metrics without going
          through the `/ask` HTTP API. The point of MCP here isn't new capability -- every tool
          below is a thin wrapper over a service this repo already has and already tests
          (`copilot.data.store`, `copilot.sql.service.TextToSqlService`) -- it's a second,
          standard-protocol front door onto the same guarded data path.
Transport : stdio only (`mcp.server.fastmcp.FastMCP.run()` default) -- the shape MCP Inspector
          and Claude Desktop both expect for a locally-run server; "remote MCP with API-key or
          OAuth auth" is explicitly the depth-track item (X1 #5), not Day 9's.

**Why every tool is hardcoded to role="viewer", not a tool parameter:** the app's own roles
(viewer/analyst/approver/admin, `policies/disclosure.yaml`) exist to answer "what may THIS
caller see", decided by the system that authenticated them (invite-code login, API-key scopes
-- Day 8). An MCP tool parameter is just a string an MCP client chooses to pass; accepting
`role` as an argument here would let any caller ask for `role="analyst"` and read confidential
data with no authentication behind that claim -- a privilege-escalation vector this project's
own least-privilege posture (R11, ADR-006) exists to close everywhere else. So this server
always queries at the lowest role (`viewer`) and never widens it. Once remote MCP auth
(X1 #5) actually authenticates a caller to a real role, that authenticated role is what should
flow in here -- not before.

**Why only 3 tools, all read-only:** the sprint spec asks for "2-3 read-only tools"; a write
tool over this data doesn't exist anywhere else in the project either (every agent here answers
questions, the Action agent only drafts, Day 7's Guardian gates even drafts behind human
approval) so there's nothing to wrap that wouldn't be a new, unreviewed write path.

Tools:
  - vendor_metrics(vendor_name)   : deterministic lookup, no LLM call, no cost.
  - portfolio_summary()           : deterministic lookup, no LLM call, no cost.
  - ask_vendor_question(question) : natural-language -> TextToSqlService -> Guardian-reviewed
                                     answer. The one tool that calls the LLM (real cost, real
                                     API key required) and the one that demonstrates the actual
                                     text-to-SQL safety stack (Day 3) end to end over MCP.

Every tool that returns real row data is still subject to the same k-threshold filtering
(`MeetsMinK`) the rest of the app applies. `vendor_metrics` filters on it directly;
`portfolio_summary` runs its SQL through the same validator `/ask` uses, so the validator adds
the filter itself and a viewer gets the same totals through either door (9 Nov 2026: before
that, this tool summed all 126 vendors while `/ask` summed the 92 that meet k).

**Same input gate as `/ask` (9 Nov 2026):** `ask_vendor_question` runs `InputGate.review` before
any LLM call -- kill switch, length, prompt-injection patterns, scope, rate limit, daily spend
cap -- and records its real cost afterwards, exactly as `Orchestrator.stream_answer` does. The
two deterministic tools make no LLM call and spend nothing, so they don't go through it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import duckdb
from mcp.server.fastmcp import FastMCP

from copilot.data import store
from copilot.guardrails.guardian import Guardian
from copilot.guardrails.input_gate import InputGate
from copilot.guardrails.policy import Role, load_policy
from copilot.llm.client import LLMClient
from copilot.llm.types import LLMCallError
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import load_rules, validate

MCP_ROLE: Role = "viewer"

mcp = FastMCP(
    "vendor-analytics",
    instructions=(
        "Read-only analytics over a beverage distributor's vendor portfolio. Every answer is "
        "scoped to the lowest-privilege role and k-anonymized (vendors below the minimum "
        "aggregation threshold are withheld). Use vendor_metrics for a single named vendor, "
        "portfolio_summary for portfolio-wide totals, and ask_vendor_question for anything "
        "else phrased as a natural-language question."
    ),
)


@lru_cache
def _get_connection() -> duckdb.DuckDBPyConnection:
    """One read-only connection per process, same `@lru_cache` lazy-singleton shape
    `copilot.api.dependencies.get_orchestrator` already uses -- `store.connect()` itself is
    safe to call more than once in a process (see its own docstring), this just avoids
    reopening the database file on every tool call."""
    return store.connect()


@lru_cache
def _get_sql_service() -> TextToSqlService:
    """Built lazily (not at import time) so the server still starts, and the two deterministic
    tools still work, when no `ANTHROPIC_API_KEY` is configured -- `LLMClient()` raises
    immediately if the key is missing; that only happens inside `ask_vendor_question`, not on
    import or server startup."""
    llm = LLMClient()
    policy = load_policy()
    return TextToSqlService(llm, con=_get_connection(), policy=policy, rules=load_rules())


@lru_cache
def _get_guardian() -> Guardian:
    return Guardian(load_policy())


@lru_cache
def _get_input_gate() -> InputGate:
    """Same construction the API uses: settings-driven limits and the shared, file-backed daily
    spend log, so MCP spend counts against the same per-role cap as `/ask` spend."""
    return InputGate()


def _run_as_mcp_role(sql: str) -> list[tuple[Any, ...]]:
    """Run fixed SQL through the validator at MCP_ROLE first, exactly as generated SQL is, so
    role rules and the k = 5 filter come from one place (policies/sql_rules.yaml) instead of
    being re-typed here. A refusal is a bug in this file's own SQL, so it raises."""
    checked = validate(sql, MCP_ROLE, load_policy(), load_rules())
    if not checked.ok or checked.sql is None:
        codes = ", ".join(v.code for v in checked.violations)
        raise RuntimeError(f"portfolio_summary SQL refused by the validator: {codes}")
    return _get_connection().execute(checked.sql).fetchall()


class _ToolReviewable:
    """Minimal stand-in for `copilot.guardrails.guardian._Reviewable` -- structurally
    duck-typed (role, answer, results, verified), same reason `orchestrator.OrchestratorResult`
    needs no shared base class with it. Built here because an MCP tool call has no
    `OrchestratorResult` of its own to hand the Guardian; constructing the four fields it
    actually reads is cheaper and clearer than inventing a fake Orchestrator run."""

    def __init__(self, *, role: Role, answer: str, verified: bool) -> None:
        self.role = role
        self.answer: str | None = answer
        self.results: list[Any] = []
        self.verified = verified


def _format_value(value: Any) -> str:
    # Thousands separators matter beyond readability here: a bare 6+ digit number
    # ("100000.0") has tripped Presidio's US_DRIVER_LICENSE recognizer in testing; "100,000.0"
    # does not -- same false-positive-avoidance reasoning `_format_rows` documents below.
    if isinstance(value, float):
        return f"{value:,}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _format_rows(rows: list[dict[str, Any]]) -> str:
    """Plain-text rendering, not a Python repr -- a raw `[{'VendorName': ...}]` dict dump is
    exactly the shape Guardian's own raw-row heuristic (docs/adr/006-guardian-design.md) is
    tuned to be suspicious of, and `copilot.insights.service.InsightService` / the golden set's
    own `reference_answer` strings already render every other answer in this project as prose
    rather than a structure dump, for the same reason.

    One formatting quirk discovered in testing, worth recording rather than silently working
    around: `<ColumnName>: <value>` directly after an all-caps multi-word value (a vendor name)
    made Presidio's spaCy-backed NER flag the vendor name itself as a false-positive LOCATION
    entity -- `"VendorName: ACME BEVERAGES, TotalRevenue: 100,000.0"` redacts, but
    `"For ACME BEVERAGES: TotalRevenue 100,000.0"` (no colon directly after the name, "For"
    framing) does not, on the same input data. So the first column of a row (almost always the
    vendor name in this schema) gets the "For X: ..." treatment; the rest are plain
    "Column value" pairs with no colon of their own.
    """
    if not rows:
        return "(query returned no rows)"
    lines: list[str] = []
    for row in rows:
        items = list(row.items())
        if len(items) <= 1:
            lines.append(", ".join(f"{k} {_format_value(v)}" for k, v in items))
            continue
        (_subject_key, subject_value), *rest = items
        rest_text = ", ".join(f"{k} {_format_value(v)}" for k, v in rest)
        lines.append(f"For {subject_value}: {rest_text}")
    return "; ".join(lines)


def _not_found(vendor_name: str) -> dict[str, Any]:
    return {
        "found": False,
        "message": (
            f"No vendor named '{vendor_name}' was found, or it has fewer than the minimum "
            "number of SKUs required to report on at this role (k-anonymity threshold)."
        ),
    }


@mcp.tool()
def vendor_metrics(vendor_name: str) -> dict[str, Any]:
    """Look up one vendor's headline metrics: revenue, margin, SKU count, revenue tier and
    Pareto band. Read-only; returns 'found: false' for an unknown vendor or one withheld by the
    k-anonymity threshold (MeetsMinK) rather than raising."""
    con = _get_connection()
    row = con.execute(
        """
        SELECT
            r.VendorName,
            r.TotalRevenue,
            r.BlendedMarginPct,
            r.NumberOfSKUs,
            t.RevenueTier,
            t.TierLabel,
            p.ParetoBand
        FROM vendor_revenue_summary r
        LEFT JOIN vendor_tiering t ON t.VendorName = r.VendorName
        LEFT JOIN vendor_pareto p ON p.VendorName = r.VendorName
        WHERE r.VendorName = ? AND r.MeetsMinK
        """,
        [vendor_name],
    ).fetchone()
    if row is None:
        return _not_found(vendor_name)
    cols = [
        "vendor_name",
        "total_revenue",
        "blended_margin_pct",
        "number_of_skus",
        "revenue_tier",
        "tier_label",
        "pareto_band",
    ]
    return {"found": True, **dict(zip(cols, row, strict=True))}


@mcp.tool()
def portfolio_summary() -> dict[str, Any]:
    """Portfolio-wide totals: vendor count, total revenue, Pareto band breakdown and SKU health
    mix. Read-only, no vendor-level data. Vendor counts and revenue cover only vendors with at
    least 5 products (the k = 5 privacy rule), the same figures a viewer gets from /ask."""
    ((vendors, revenue),) = _run_as_mcp_role(
        "SELECT count(*), round(sum(TotalRevenue), 2) FROM vendor_revenue_summary"
    )
    pareto_rows = _run_as_mcp_role(
        "SELECT ParetoBand, count(*) FROM vendor_pareto GROUP BY ParetoBand ORDER BY ParetoBand"
    )
    health_rows = _run_as_mcp_role(
        "SELECT HealthStatus, SKUs, SharePct FROM portfolio_health_mix ORDER BY SharePct DESC"
    )
    return {
        "vendor_count": vendors,
        "total_revenue": revenue,
        "pareto_bands": {band: count for band, count in pareto_rows},
        "sku_health_mix": [
            {"health_status": status, "skus": skus, "share_pct": share}
            for status, skus, share in health_rows
        ],
        "note": (
            "Vendor count, revenue and Pareto bands leave out vendors with fewer than 5 "
            "products (the k = 5 privacy rule). The SKU health mix is a portfolio-wide table."
        ),
    }


@mcp.tool()
def ask_vendor_question(question: str) -> dict[str, Any]:
    """Ask a free-form question about the vendor portfolio in plain English. Runs the same
    text-to-SQL safety stack the rest of the app uses (schema-linked, validated, self-correcting
    SQL generation -- docs/specs/text_to_sql_safety.md) and the same mandatory Guardian final
    pass (docs/adr/006-guardian-design.md) before returning an answer. Requires a configured
    Anthropic API key (real LLM call, real cost); returns an explicit error, not a guess, if one
    isn't set. Checked first by the same input gate as /ask; a blocked question never reaches
    the LLM."""
    gate = _get_input_gate()
    gate_verdict = gate.review(question, MCP_ROLE)
    if gate_verdict.outcome == "block":
        return {
            "answered": False,
            "blocked_by": "input_gate",
            "reason_codes": gate_verdict.reason_codes,
            "message": gate_verdict.message,
        }

    try:
        service = _get_sql_service()
    except LLMCallError as exc:
        return {"answered": False, "error": f"no Anthropic API key configured: {exc}"}

    result = service.answer(question, role=MCP_ROLE)
    gate.record_spend(MCP_ROLE, result.total_cost_usd)

    if result.abstained:
        return {"answered": False, "abstain_reason": result.abstain_reason}

    rows = result.rows or []
    draft_answer = _format_rows(rows)
    reviewable = _ToolReviewable(role=MCP_ROLE, answer=draft_answer, verified=True)
    verdict = _get_guardian().review(reviewable)

    return {
        "answered": verdict.outcome == "allow",
        "guardian_outcome": verdict.outcome,
        "answer": verdict.safe_answer,
        "sql": result.sql,
        "row_count": len(rows),
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
