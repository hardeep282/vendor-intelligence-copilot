"""Day 6 step 1: TaskSpec / AgentResult -- the typed handoff contracts every specialist and the
Orchestrator pass between each other.

Purpose : master prompt C3 requires agents to "never pass free text to each other." Every
          specialist node in `copilot.agents.orchestrator` takes a `TaskSpec` in and returns an
          `AgentResult` out -- no bare strings crossing a node boundary. `AgentResult.data_classes`
          is what the Guardian (Day 7) will compare against the requesting role and the answer's
          audience (C3's "provenance check"), so every specialist must fill it honestly from
          `DisclosurePolicy`, never leave it empty because "nothing felt sensitive."
Inputs  : none at import time -- these are pure data contracts.
Outputs : TaskSpec, AgentResult, AgentStatus, and the budget types specialists are constructed
          with.

Why a new file instead of reusing one of the existing *Result classes (`TextToSqlResult`,
`CorrectiveRagResult`, `ModelSelectionResult`): those are each service's own return type and stay
exactly as they are -- the orchestrator wraps each one's output into a shared `AgentResult`
envelope rather than those services growing orchestrator-shaped fields they don't otherwise need.
This mirrors how `copilot.llm.types.CallMetrics` is the one shared instrumentation shape that
every call path returns, regardless of which prompt it ran.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from copilot.guardrails.policy import DataClass, Role
from copilot.llm.client import Effort

AgentName = Literal[
    "data_analyst",
    "forecasting_risk",
    "inventory_planning",
    "knowledge",
    "action",
]

AgentStatus = Literal["ok", "partial", "failed"]


class AgentBudget(BaseModel):
    """Per-agent resource ceiling (C3: "own step/token/cost/latency budget"), enforced by the
    Orchestrator (Day 6 step 5, `copilot.agents.orchestrator._run_specialist`), not by the
    specialist itself: a specialist whose result overran `max_cost_usd`/`max_llm_calls` gets
    downgraded `ok` -> `partial` with the overage named in `gaps` after it returns, and
    `max_latency_s` additionally bounds how long the Orchestrator will *wait* on it -- a
    specialist still running past that deadline is treated as `status="failed"`, not awaited
    indefinitely (real cancellation of arbitrary synchronous specialist code isn't possible from
    here; the bound is on how long the Orchestrator waits, not a guarantee the specialist's own
    thread stops).

    `effort` is this generation's per-call sampling lever, substituting for the
    `temperature` the sprint doc originally asked for -- see `copilot.llm.client`'s module
    docstring: this Anthropic SDK/model generation has no `temperature` parameter at all.
    `None` lets each specialist fall back to its own prompt's `effort` default.
    """

    max_steps: int = 1
    max_llm_calls: int = 3
    max_cost_usd: float = 0.05
    max_latency_s: float = 30.0
    effort: Effort | None = None


class TaskSpec(BaseModel):
    """What the Orchestrator hands one specialist. `constraints` carries anything that narrows
    the task beyond `objective` (e.g. a specific vendor name, a time window) -- kept as a dict
    rather than free text so a specialist's node can read a known key without re-parsing prose.
    """

    task_id: str
    agent: AgentName
    objective: str
    inputs: dict[str, str] = Field(default_factory=dict)
    constraints: dict[str, str] = Field(default_factory=dict)
    role: Role
    budget: AgentBudget = Field(default_factory=AgentBudget)
    allowed_data_classes: list[DataClass] = Field(default_factory=list)


class AgentResult(BaseModel):
    """What every specialist returns to the Orchestrator. `findings` is the condensed,
    natural-language result (C3 target: <=1500 tokens) -- heavy intermediate state (full SQL
    rows, every retrieved chunk) stays inside the specialist and is summarised here, never
    forwarded wholesale into the Orchestrator's context.

    `data_classes` is never inferred by the Orchestrator or the Guardian -- each specialist
    fills it itself from the `DisclosurePolicy` tables/chunks it actually touched, because only
    the specialist that ran the query or retrieval knows what was really read.
    """

    task_id: str
    agent: AgentName
    status: AgentStatus
    findings: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    gaps: list[str] = Field(default_factory=list)
    data_classes: list[DataClass] = Field(default_factory=list)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    llm_calls: int = 0

    def exceeds(self, budget: AgentBudget) -> bool:
        """True if this result's own accounting is over the budget it was given -- the check a
        specialist node runs on itself before returning, to decide `ok` vs `partial`.
        """
        return (
            self.cost_usd > budget.max_cost_usd
            or self.latency_s > budget.max_latency_s
            or self.llm_calls > budget.max_llm_calls
        )
