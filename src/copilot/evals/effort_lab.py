"""Effort lab (Day 3 step 8, per ADR-005's correction): sweep `output_config.effort` across
its 5 values instead of a temperature sweep -- this model generation has no `temperature`,
`top_p` or `top_k` parameter (see `copilot.llm.client`'s module docstring), so `effort` is the
nearest per-call lever, and it trades reasoning depth for latency/cost rather than output
diversity at fixed sampling. That difference is exactly what this lab measures.

Purpose : run the same golden questions at every effort level and compare, on the SAME
          metrics the sprint plan specified for the original temperature lab: execution
          accuracy, grounding (here, `leakage_free` -- see `copilot.evals.evaluators`'s
          docstring for why the two are scored separately), output diversity, latency, cost.
Inputs  : a `TextToSqlService`, the golden questions to sweep, and how many times to repeat
          each one per effort level (`repeats`; >1 is what makes "output diversity"
          measurable -- at `repeats=1` there's nothing to compare a single run against, so
          `sql_diversity` is left `None` rather than reported as a meaningless 1.0 or 0.0).
Outputs : an `EffortLabReport` -- every individual run plus a summary row per effort level.
"""

from __future__ import annotations

from pydantic import BaseModel

from copilot.evals.evaluators import execution_accuracy, leakage_free
from copilot.evals.golden import GoldenQuestion
from copilot.guardrails.policy import DisclosurePolicy
from copilot.llm.client import Effort
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import SqlRules

EFFORT_LEVELS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


class RunRecord(BaseModel):
    question_id: str
    effort: str
    repeat: int
    execution_accuracy: float
    leakage_free: float
    cost_usd: float
    latency_s: float
    self_corrections: int
    sql: str | None


class EffortLevelSummary(BaseModel):
    effort: str
    runs: int
    execution_accuracy_rate: float
    leakage_free_rate: float
    avg_cost_usd: float
    avg_latency_s: float
    avg_self_corrections: float
    # Average, across questions, of (distinct SQL strings produced / repeats) for that
    # question at this effort level. None when repeats == 1 -- nothing to compare against.
    sql_diversity: float | None = None


class EffortLabReport(BaseModel):
    records: list[RunRecord]
    by_effort: list[EffortLevelSummary]


def _diversity_for_effort(
    rows: list[RunRecord], questions: list[GoldenQuestion], repeats: int
) -> float | None:
    if repeats <= 1:
        return None
    per_question: list[float] = []
    for q in questions:
        q_rows = [r for r in rows if r.question_id == q.id]
        if not q_rows:
            continue
        distinct = len({r.sql for r in q_rows})
        per_question.append(distinct / len(q_rows))
    return sum(per_question) / len(per_question) if per_question else None


def run_effort_lab(
    service: TextToSqlService,
    questions: list[GoldenQuestion],
    policy: DisclosurePolicy,
    rules: SqlRules,
    efforts: tuple[Effort, ...] = EFFORT_LEVELS,
    repeats: int = 1,
) -> EffortLabReport:
    """Run every question at every effort level, `repeats` times each, and score each run."""
    records: list[RunRecord] = []
    for effort in efforts:
        for q in questions:
            for repeat in range(repeats):
                result = service.answer(q.question, role=q.role, effort=effort)
                acc = execution_accuracy(result, q)
                leak = leakage_free(result, q, policy, rules)
                records.append(
                    RunRecord(
                        question_id=q.id,
                        effort=effort,
                        repeat=repeat,
                        execution_accuracy=acc.score,
                        leakage_free=leak.score,
                        cost_usd=result.total_cost_usd,
                        latency_s=result.total_latency_s,
                        self_corrections=result.self_corrections,
                        sql=result.sql,
                    )
                )

    by_effort: list[EffortLevelSummary] = []
    for effort in efforts:
        rows = [r for r in records if r.effort == effort]
        n = len(rows)
        if n == 0:
            continue
        by_effort.append(
            EffortLevelSummary(
                effort=effort,
                runs=n,
                execution_accuracy_rate=sum(r.execution_accuracy for r in rows) / n,
                leakage_free_rate=sum(r.leakage_free for r in rows) / n,
                avg_cost_usd=sum(r.cost_usd for r in rows) / n,
                avg_latency_s=sum(r.latency_s for r in rows) / n,
                avg_self_corrections=sum(r.self_corrections for r in rows) / n,
                sql_diversity=_diversity_for_effort(rows, questions, repeats),
            )
        )

    return EffortLabReport(records=records, by_effort=by_effort)
