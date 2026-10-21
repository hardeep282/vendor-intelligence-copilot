"""InsightService: a grounded narrative insight for one vendor at a time.

Purpose : the refactor of the legacy analytics repo's `vendor_insights.py` (ADR-000 item 5)
          into a typed, testable service in this codebase. The model id is config (prompt YAML),
          not a hardcoded string, and every number the model is allowed to use is handed to it
          explicitly -- nothing is looked up by the model itself.
Inputs  : a vendor name and the caller's role (controls the minimum-aggregation gate).
Outputs : `VendorInsight` (forced structured output) + `CallMetrics`, or `VendorNotFoundError`.

Grounding, not retrieval: this only reads the three `internal`-class tables already allowed for
a viewer (disclosure.yaml), joins them by vendor name, and masks any field whose row fails the
k-threshold for the caller's role -- the LLM never sees a number it isn't allowed to use, and is
told explicitly when one was withheld rather than being handed a silent gap.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import anthropic
import duckdb
from pydantic import BaseModel, Field

from copilot.data import store
from copilot.guardrails.policy import DisclosurePolicy, Role, load_policy
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics, LLMCallError, StructuredOutputError

log = logging.getLogger("copilot.insights")

# Day 8, Addendum A2 §1.1 "graceful degradation": the narration step can fail even after
# LLMClient's own retries and fallback model are exhausted (provider outage covering every
# configured model). These are exactly the exceptions worth degrading on -- an outage, a
# repeated malformed/invalid response, or (defensively) a missing key -- not a bug in our own
# code, which should still crash loudly.
_DEGRADE_ON: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.ServiceUnavailableError,
    anthropic.OverloadedError,
    anthropic.DeadlineExceededError,
    StructuredOutputError,
    LLMCallError,
)

# Grounding sources for one insight -- all three are tagged `internal` in disclosure.yaml, so a
# viewer-role insight never has to reach for a confidential or restricted table.
_SOURCE_TABLES: tuple[str, ...] = (
    "vendor_revenue_summary",
    "vendor_tiering",
    "vendor_profit_leakage",
)

_WITHHELD = {"withheld": "below minimum aggregation threshold"}


class VendorNotFoundError(ValueError):
    """Raised when the vendor name matches no row in any of the source tables."""


class VendorInsight(BaseModel):
    """Forced structured output: a grounded narrative plus its citations."""

    vendor_name: str
    headline: str = Field(max_length=120)
    narrative: str
    key_metrics_cited: list[str] = Field(
        default_factory=list,
        description="Exact input field names the narrative's numbers came from.",
    )
    risk_flags: list[str] = Field(default_factory=list)
    # Day 8, Addendum A2 §1.1 "graceful degradation": True for every normal response. Set False
    # only when the LLM narration step failed outright (after LLMClient's own retries and
    # fallback-model attempt, if one is configured) -- `narrative` then holds the deterministic
    # `vendor_data_block` as plain JSON instead of a model-written sentence, so the caller still
    # gets the real, correct numbers rather than an HTTP error for a question the data layer
    # could answer perfectly well on its own. `key_metrics_cited`/`risk_flags` are empty in this
    # case (nothing to cite -- there was no narration), not fabricated.
    narration_available: bool = True


def _vendor_row(
    con: duckdb.DuckDBPyConnection, table: str, vendor_name: str
) -> dict[str, Any] | None:
    cur = con.execute(f"SELECT * FROM {table} WHERE VendorName = ?", [vendor_name])  # noqa: S608
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row, strict=True)) if row is not None else None


def gather_vendor_data(
    con: duckdb.DuckDBPyConnection,
    vendor_name: str,
    policy: DisclosurePolicy,
    role: Role,
) -> dict[str, dict[str, Any]]:
    """One dict per source table that has a row for this vendor.

    A field hidden by the k-threshold is replaced with `_WITHHELD`, never dropped -- the prompt
    states the rule ("withheld" means do not guess), so a silent gap and an actually-small number
    are never confusable to the model or, downstream, to the reader.
    """
    data: dict[str, dict[str, Any]] = {}
    k_applies = policy.k_applies(role)
    for table in _SOURCE_TABLES:
        row = _vendor_row(con, table, vendor_name)
        if row is None:
            continue
        meets_k = bool(row.get("MeetsMinK", True))
        if k_applies and not meets_k:
            data[table] = dict(_WITHHELD)
        else:
            data[table] = {k: v for k, v in row.items() if k != "MeetsMinK"}
    if not data:
        raise VendorNotFoundError(f"no vendor named {vendor_name!r} in the snapshot")
    return data


class InsightService:
    """Depends on an `LLMClient` and, optionally, a DuckDB connection + policy -- both injectable
    so tests never open the real snapshot or call the real API.
    """

    def __init__(
        self,
        llm: LLMClient,
        con: duckdb.DuckDBPyConnection | None = None,
        policy: DisclosurePolicy | None = None,
    ) -> None:
        self._llm = llm
        self._con = con if con is not None else store.connect()
        self._policy = policy if policy is not None else load_policy()

    def vendor_insight(
        self,
        vendor_name: str,
        role: Role = "viewer",
        effort: Effort | None = None,
    ) -> tuple[VendorInsight, CallMetrics]:
        """Fetch this vendor's grounding data and ask the model for a cited narrative.

        Degrades gracefully (A2 §1.1) rather than raising if narration fails outright: the
        caller still gets the real, computed `data` back, flagged `narration_available=False`,
        instead of a 500 for a question Python already had the correct answer to.
        """
        data = gather_vendor_data(self._con, vendor_name, self._policy, role)
        prompt = load_prompt("vendor_insight")
        system = prompt.render_system(role=role)
        data_block = json.dumps(data, indent=2, default=str)
        user = prompt.render_user(vendor_name=vendor_name, vendor_data_block=data_block)
        try:
            insight, metrics = self._llm.structured(
                model=prompt.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_model=VendorInsight,
                max_tokens=prompt.max_tokens,
                effort=effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            )
        except _DEGRADE_ON as exc:
            log.warning(
                "insights.narration_unavailable vendor=%s role=%s error=%s: %s",
                vendor_name,
                role,
                type(exc).__name__,
                exc,
            )
            degraded = VendorInsight(
                vendor_name=vendor_name,
                headline=f"{vendor_name}: narration unavailable, computed data below",
                narrative=data_block,
                narration_available=False,
            )
            # No metrics to report -- the call never produced usable output. Zeros, not a fake
            # successful-looking CallMetrics row (A2's own "never invent numbers" rule).
            return degraded, CallMetrics(
                model=prompt.model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                ttft_s=0.0,
                total_latency_s=0.0,
                stop_reason="degraded",
            )
        return cast("VendorInsight", insight), metrics


__all__ = ["InsightService", "VendorInsight", "VendorNotFoundError", "gather_vendor_data"]
