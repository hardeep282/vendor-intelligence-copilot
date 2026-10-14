"""Schema linking: which tables and columns a role may even be told about.

Purpose : a text-to-SQL model can only write a safe query against a schema it's actually
          shown. Showing it every table (including ones the caller's role can't read) just
          invites the model to write SQL the validator then has to reject -- wasted repair
          loops, and a role boundary leaking into the prompt itself. This builds the schema
          card from the two things that are already the source of truth for column names and
          role access, instead of a hand-maintained third copy.
Inputs  : data/snapshot/MANIFEST.json (table -> columns, written by scripts/build_snapshot.py)
          and the disclosure policy (table -> data class, role -> allowed classes).
Outputs : a compact text block for the prompt, and the set of table names a role may see.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from copilot.guardrails.policy import DisclosurePolicy, Role
from copilot.settings import get_settings

# Never shown to the model, whatever the role: our own bookkeeping, not query-able data.
_HIDDEN_COLUMNS = frozenset({"MeetsMinK"})


class TableSchema(BaseModel):
    name: str
    data_class: str
    columns: list[str]


def _manifest_path() -> Path:
    return get_settings().snapshot_dir / "MANIFEST.json"


def visible_tables(
    policy: DisclosurePolicy, role: Role, manifest_path: Path | None = None
) -> list[TableSchema]:
    """Tables + columns the given role is allowed to read, in a stable order."""
    manifest = json.loads((manifest_path or _manifest_path()).read_text(encoding="utf-8"))
    out: list[TableSchema] = []
    for name in sorted(manifest["tables"]):
        tag = policy.tables.get(name)
        if tag is None or not policy.can_view(role, tag.data_class):
            continue
        columns = [c for c in manifest["tables"][name]["columns"] if c not in _HIDDEN_COLUMNS]
        out.append(TableSchema(name=name, data_class=tag.data_class, columns=columns))
    return out


def build_schema_card(
    policy: DisclosurePolicy, role: Role, manifest_path: Path | None = None
) -> str:
    """Render `visible_tables()` as the text block the text-to-SQL prompt shows the model."""
    tables = visible_tables(policy, role, manifest_path)
    if not tables:
        return "(no tables are readable by this role)"
    lines = [f"{t.name} [{t.data_class}]: {', '.join(t.columns)}" for t in tables]
    return "\n".join(lines)
