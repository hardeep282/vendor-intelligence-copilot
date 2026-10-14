"""Day 6 step 7: the 10 multi-hop golden questions for the multi-agent system -- schema and
loader.

Purpose : distinct from `copilot.evals.golden`'s "multi_hop" category (gq-031..034), which
          means multi-step *SQL* answered by one specialist (`TextToSqlService` alone). These
          questions are multi-*agent*-hop: each one needs the Orchestrator to plan 2+ of the
          five C3 specialists and combine their findings into one answer -- the thing nothing
          before Day 6 could even attempt, since Day 1-5 had no Orchestrator to fan a question
          out across specialists at all.
Inputs  : evals/datasets/orchestrator_golden_v1.jsonl.
Outputs : typed `OrchestratorGoldenQuestion` objects.

Each question's `expected_agents` is a *structural* check, not an answer-accuracy one: did the
Orchestrator's plan actually involve every specialist this question needs, not just the easiest
one? This dataset makes no claim about what the final answer should literally say -- there is
no `expected_rows`/`reference_answer` here the way `copilot.evals.golden.GoldenQuestion` has for
single-agent text-to-SQL, because grading multi-agent answer *content* against a fixed reference
is Day 6 step 7's own stretch goal, not its floor; `scripts/run_orchestrator_golden.py` reports
plan coverage, verification status, and cost/latency -- real signals a human reviewing the
printed answers can combine with, rather than a brittle exact-match this dataset would need to
hand-maintain across every prompt change.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator

from copilot.agents.contracts import AgentName
from copilot.guardrails.policy import Role
from copilot.settings import REPO_ROOT

ORCHESTRATOR_GOLDEN_PATH = REPO_ROOT / "evals" / "datasets" / "orchestrator_golden_v1.jsonl"


class OrchestratorGoldenQuestion(BaseModel):
    id: str
    question: str
    role: Role
    expected_agents: list[AgentName]
    notes: str = ""

    @field_validator("expected_agents")
    @classmethod
    def _at_least_two_agents(cls, v: list[AgentName]) -> list[AgentName]:
        if len(v) < 2:
            raise ValueError(
                "a multi-hop golden question needs >=2 expected_agents -- a single-specialist "
                "question belongs in copilot.evals.golden/rag_golden instead"
            )
        if len(set(v)) != len(v):
            raise ValueError(f"expected_agents has duplicates: {v}")
        return v


def load_orchestrator_golden(
    path: Path = ORCHESTRATOR_GOLDEN_PATH,
) -> list[OrchestratorGoldenQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [OrchestratorGoldenQuestion.model_validate_json(line) for line in lines if line.strip()]


__all__ = ["ORCHESTRATOR_GOLDEN_PATH", "OrchestratorGoldenQuestion", "load_orchestrator_golden"]
