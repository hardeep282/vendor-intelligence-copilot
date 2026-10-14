"""Knowledge corpus loader.

Purpose : read the RAG source documents from knowledge/ (data dictionary, metric definitions,
          decision log, methodology, synthetic vendor contracts) and parse each one's YAML
          frontmatter + Markdown body into a typed object. This is the raw-document layer;
          chunking (Day 4 step 2) reads its output, not the files directly.
Inputs  : the knowledge/ directory tree (default: <repo root>/knowledge).
Outputs : a list of KnowledgeDoc, one per .md file, each carrying its disclosure metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator

from copilot.guardrails.policy import DataClass, Role, load_policy
from copilot.settings import REPO_ROOT

DEFAULT_CORPUS_DIR = REPO_ROOT / "knowledge"

DocType = Literal[
    "data_dictionary", "metric_definitions", "decision_log", "methodology", "vendor_contract"
]

_FRONTMATTER_DELIM = "---\n"


class CorpusError(ValueError):
    """A knowledge document is missing or malformed frontmatter."""


class KnowledgeDoc(BaseModel):
    path: Path
    doc_type: DocType
    vendor: str | None
    version: int
    data_class: DataClass
    allowed_roles: list[Role]
    body: str  # Markdown body, frontmatter stripped. Chunking (step 2) splits this by heading.

    @field_validator("allowed_roles")
    @classmethod
    def _not_empty(cls, v: list[Role]) -> list[Role]:
        if not v:
            raise ValueError("allowed_roles must not be empty")
        return v


def _parse_frontmatter(text: str, path: Path) -> tuple[dict[str, object], str]:
    if not text.startswith(_FRONTMATTER_DELIM):
        raise CorpusError(f"{path}: missing opening '---' frontmatter delimiter")
    end = text.find("\n---\n", len(_FRONTMATTER_DELIM))
    if end == -1:
        raise CorpusError(f"{path}: missing closing '---' frontmatter delimiter")
    raw_meta = text[len(_FRONTMATTER_DELIM) : end]
    body = text[end + len("\n---\n") :].lstrip("\n")
    meta = yaml.safe_load(raw_meta)
    if not isinstance(meta, dict):
        raise CorpusError(f"{path}: frontmatter did not parse to a mapping")
    return meta, body


def load_doc(path: Path) -> KnowledgeDoc:
    """Parse one knowledge document. Raises CorpusError on malformed frontmatter."""
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text, path)
    try:
        return KnowledgeDoc(path=path, body=body, **meta)
    except Exception as exc:  # pydantic ValidationError, KeyError from missing fields
        raise CorpusError(f"{path}: {exc}") from exc


def load_corpus(corpus_dir: Path = DEFAULT_CORPUS_DIR) -> list[KnowledgeDoc]:
    """Load every .md file under corpus_dir, recursively, sorted by path for determinism."""
    paths = sorted(corpus_dir.rglob("*.md"))
    return [load_doc(p) for p in paths]


def check_corpus_against_policy(docs: list[KnowledgeDoc]) -> None:
    """Raise CorpusError if any doc's allowed_roles disagrees with the live disclosure policy.

    Catches drift: if policies/disclosure.yaml changes a role's access to a data_class, the
    corpus's hand-authored allowed_roles list can silently go stale. This recomputes the correct
    role list from the policy and compares it to what each document declares.
    """
    policy = load_policy()
    for doc in docs:
        expected = sorted(role for role in policy.roles if policy.can_view(role, doc.data_class))
        actual = sorted(doc.allowed_roles)
        if actual != expected:
            raise CorpusError(
                f"{doc.path}: allowed_roles {actual} does not match policy-derived "
                f"{expected} for data_class '{doc.data_class}'"
            )
