"""Disclosure policy loader.

Purpose : parse policies/disclosure.yaml into typed objects and answer "may this role see this?".
Inputs  : the YAML policy file (default: policies/disclosure.yaml).
Outputs : a validated `DisclosurePolicy`; the Guardian (Day 7) and the tool layer both call it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from copilot.settings import REPO_ROOT

DataClass = Literal["public", "internal", "confidential", "restricted"]
Role = Literal["anonymous", "viewer", "analyst", "approver", "admin"]
DEFAULT_POLICY_PATH = REPO_ROOT / "policies" / "disclosure.yaml"


class MinAggregation(BaseModel):
    k: int
    applies_to_roles: list[Role]


class VendorFacing(BaseModel):
    allowed_classes: list[DataClass]
    allow_own_contract_terms: bool


class TableTag(BaseModel):
    data_class: DataClass
    columns: dict[str, DataClass] = {}


class Canary(BaseModel):
    prefix: str


class DisclosurePolicy(BaseModel):
    version: int
    classes: list[DataClass]
    roles: dict[Role, list[DataClass]]
    min_aggregation: MinAggregation
    vendor_facing_audience: VendorFacing
    tables: dict[str, TableTag]
    restricted_names: list[str]
    canary: Canary

    @model_validator(mode="after")
    def _nobody_reads_restricted(self) -> DisclosurePolicy:
        for role, classes in self.roles.items():
            if "restricted" in classes:
                raise ValueError(f"role '{role}' may not be granted the restricted class")
        return self

    def can_view(self, role: Role, data_class: DataClass) -> bool:
        """True if `role` may read data of `data_class`. Restricted is always False."""
        return data_class != "restricted" and data_class in self.roles.get(role, [])

    def class_of(self, table: str, column: str | None = None) -> DataClass:
        """Class of a table, or of one column when it has an override. Untagged means restricted."""
        tag = self.tables.get(table)
        if tag is None:
            return "restricted"  # fail closed: anything not catalogued is off limits
        if column is not None and column in tag.columns:
            return tag.columns[column]
        return tag.data_class

    def k_applies(self, role: Role) -> bool:
        return role in self.min_aggregation.applies_to_roles


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> DisclosurePolicy:
    """Parse and validate the policy file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["min_aggregation"] = {
        "k": raw["min_aggregation"]["k"],
        "applies_to_roles": raw["min_aggregation"]["applies_to_roles"],
    }
    # The YAML uses `class:` (a Python keyword); map it to `data_class`.
    raw["tables"] = {
        name: {"data_class": t["class"], "columns": t.get("columns", {})}
        for name, t in raw["tables"].items()
    }
    return DisclosurePolicy.model_validate(raw)
