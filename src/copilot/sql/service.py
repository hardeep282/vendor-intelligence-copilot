"""TextToSqlService: one business question -> one validated DuckDB query -> real rows.

Purpose : Day 3 step 4 (docs/specs/text_to_sql_safety.md). Turns a question into SQL with the
          model shown only its role's tables (schema linking, `copilot.sql.schema`) and 3
          similar verified pairs (`copilot.sql.examples`), validates the result through every
          layer in `copilot.sql.validator` before it ever runs, and feeds a rejected query's
          exact violations back to the model instead of giving up on the first miss (layer 4,
          "self-correction"). Still abstains rather than guess once the retry budget is spent.
Inputs  : a question, the caller's role, an optional `effort` override.
Outputs : `TextToSqlResult` -- either real rows from a validated query, or an explicit
          abstention with the reason (a validator rejection the model couldn't fix, or the
          model declining on its own because the question is outside the schema or coverage).
"""

from __future__ import annotations

from typing import Any, cast

import duckdb
from anthropic.types import MessageParam
from pydantic import BaseModel

from copilot.data import store
from copilot.evals.golden import run_rows
from copilot.guardrails.canary import canary_line
from copilot.guardrails.policy import DisclosurePolicy, Role, load_policy
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import Prompt, load_prompt
from copilot.llm.types import CallMetrics
from copilot.sql.examples import format_examples, retrieve_examples
from copilot.sql.schema import build_schema_card
from copilot.sql.validator import SqlRules, Violation, load_rules, validate

# Layer 4 of the spec: "max 2 retries" after the first attempt, then abstain with the reason.
MAX_SELF_CORRECTIONS = 2


class SqlGeneration(BaseModel):
    """Forced structured output for the text_to_sql prompt."""

    sql: str | None = None
    assumptions: list[str] = []
    abstain_reason: str | None = None


class TextToSqlResult(BaseModel):
    question: str
    role: Role
    sql: str | None = None
    rows: list[dict[str, Any]] | None = None
    assumptions: list[str] = []
    abstained: bool
    abstain_reason: str | None = None
    truncated: bool = False
    self_corrections: int = 0
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    llm_calls: int = 0


def _feedback(violations: list[Violation]) -> str:
    reasons = "; ".join(f"{v.code}: {v.message}" for v in violations)
    return (
        f"That SQL was rejected: {reasons}\n"
        "Write a corrected query, or leave `sql` null with an `abstain_reason` if a correct "
        "query against the given schema genuinely isn't possible."
    )


class TextToSqlService:
    def __init__(
        self,
        llm: LLMClient,
        con: duckdb.DuckDBPyConnection | None = None,
        policy: DisclosurePolicy | None = None,
        rules: SqlRules | None = None,
    ) -> None:
        self._llm = llm
        self._con = con if con is not None else store.connect()
        self._policy = policy if policy is not None else load_policy()
        self._rules = rules if rules is not None else load_rules()

    def answer(
        self, question: str, role: Role = "viewer", effort: Effort | None = None
    ) -> TextToSqlResult:
        prompt = load_prompt("text_to_sql")
        schema_card = build_schema_card(self._policy, role)
        examples_block = format_examples(retrieve_examples(question, role))
        system = prompt.render_system(
            role=role, schema_card=schema_card, examples_block=examples_block
        ) + canary_line("data_analyst")
        convo: list[MessageParam] = [
            {"role": "user", "content": prompt.render_user(question=question)}
        ]

        violations: list[Violation] = []
        total_cost = 0.0
        total_latency = 0.0
        for attempt in range(MAX_SELF_CORRECTIONS + 1):
            generation, metrics = self._call(prompt, system, convo, effort)
            total_cost += metrics.cost_usd
            total_latency += metrics.total_latency_s

            if generation.sql is None:
                return TextToSqlResult(
                    question=question,
                    role=role,
                    assumptions=generation.assumptions,
                    abstained=True,
                    abstain_reason=generation.abstain_reason or "model abstained without a reason",
                    self_corrections=attempt,
                    total_cost_usd=total_cost,
                    total_latency_s=total_latency,
                    llm_calls=attempt + 1,
                )

            result = validate(generation.sql, role, self._policy, self._rules)
            if result.ok:
                rows = run_rows(self._con, result.sql)
                return TextToSqlResult(
                    question=question,
                    role=role,
                    sql=result.sql,
                    rows=rows,
                    assumptions=generation.assumptions,
                    abstained=False,
                    truncated=result.truncated,
                    self_corrections=attempt,
                    total_cost_usd=total_cost,
                    total_latency_s=total_latency,
                    llm_calls=attempt + 1,
                )

            violations = result.violations
            if attempt >= MAX_SELF_CORRECTIONS:
                break
            convo = [
                *convo,
                {"role": "assistant", "content": generation.sql},
                {"role": "user", "content": _feedback(violations)},
            ]

        return TextToSqlResult(
            question=question,
            role=role,
            abstained=True,
            abstain_reason=(
                f"validator rejected the query after {MAX_SELF_CORRECTIONS} self-corrections: "
                + "; ".join(f"{v.code}: {v.message}" for v in violations)
            ),
            self_corrections=MAX_SELF_CORRECTIONS,
            total_cost_usd=total_cost,
            total_latency_s=total_latency,
            llm_calls=MAX_SELF_CORRECTIONS + 1,
        )

    def _call(
        self, prompt: Prompt, system: str, convo: list[MessageParam], effort: Effort | None
    ) -> tuple[SqlGeneration, CallMetrics]:
        result = self._llm.structured(
            model=prompt.model,
            system=system,
            messages=convo,
            output_model=SqlGeneration,
            max_tokens=prompt.max_tokens,
            effort=effort or prompt.effort,
            cache_system=prompt.cache_system,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
        )
        return cast("tuple[SqlGeneration, CallMetrics]", result)
