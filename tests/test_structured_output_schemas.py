"""Every structured-output model, run through the Anthropic SDK's own strict-schema step.

Added 2 Nov 2026. `PlannedTask.constraints` was an open `dict[str, str]`; the SDK's
`transform_schema` (what `output_format=` sends to the API) rewrote it as an object with no
properties and `additionalProperties: false`, so the model could only ever send `{}`. Every
other test used a fake LLM that never runs this step, so nothing caught it for a week of real
runs. These tests run the real step on every model the code passes as `output_model`.
"""

from __future__ import annotations

from typing import Any

import pytest
from anthropic import transform_schema
from pydantic import BaseModel

from copilot.agents.model_selection import ModelCritique, ModelProposal
from copilot.agents.orchestrator import DraftAnswer, OrchestratorPlan, VerifierVerdict
from copilot.agents.specialists import ActionDraft
from copilot.evals.model_selection_quality import ReasoningGrade
from copilot.evals.rag_quality import ContextRecallGrade, FaithfulnessGrade
from copilot.insights.service import VendorInsight
from copilot.rag.corrective import GroundedAnswer, QueryRewrite, RetrievalGrade
from copilot.sql.service import SqlGeneration

OUTPUT_MODELS: list[type[BaseModel]] = [
    ActionDraft,
    ContextRecallGrade,
    DraftAnswer,
    FaithfulnessGrade,
    GroundedAnswer,
    ModelCritique,
    ModelProposal,
    OrchestratorPlan,
    QueryRewrite,
    ReasoningGrade,
    RetrievalGrade,
    SqlGeneration,
    VendorInsight,
    VerifierVerdict,
]


def _closed_empty_objects(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "object" and not node.get("properties"):
            found.append(path or "<root>")
        for key, value in node.items():
            found += _closed_empty_objects(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _closed_empty_objects(value, f"{path}[{i}]")
    return found


@pytest.mark.parametrize("model", OUTPUT_MODELS, ids=lambda m: m.__name__)
def test_no_structured_output_schema_has_a_closed_empty_object(model: type[BaseModel]) -> None:
    """An object with no properties, after the SDK's strict transform, can only ever be {}."""
    assert _closed_empty_objects(transform_schema(model)) == []


def test_the_plan_schema_lets_the_model_send_every_constraint_the_specialists_read() -> None:
    schema = transform_schema(OrchestratorPlan)
    fields = set(schema["$defs"]["PlanConstraints"]["properties"])
    assert {
        "vendor_name",
        "level",
        "draft_type",
        "horizon_months",
        "service_level",
        "lead_time_periods",
        "ordering_cost_per_order",
        "holding_cost_per_unit_per_year",
        "run_risk_classifier",
        "context",
    } <= fields
