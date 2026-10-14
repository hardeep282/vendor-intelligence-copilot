"""Retrieve similar golden question/SQL pairs to show as few-shot examples.

Purpose : grounding a text-to-SQL prompt in 3 examples that are actually similar to the
          question being asked teaches the model the house style (exact column names, the
          ratio-of-sums pattern, how a withheld/empty result is phrased) far more cheaply than
          a long rules essay. Retrieval here is deliberately simple -- lexical overlap, not
          embeddings -- because the golden set is 40 rows: a vector index would add a
          dependency and a build step to retrieve from a set small enough to score directly.
Inputs  : the caller's question and role, the golden set (evals/datasets/golden_v1.jsonl).
Outputs : up to `k` `GoldenQuestion`s, most-similar first, restricted to ones with real SQL
          and a role no more privileged than the caller's (never teach a viewer the analyst
          query shape for a table they can't read).
"""

from __future__ import annotations

import re

from copilot.evals.golden import GoldenQuestion, load_golden
from copilot.guardrails.policy import Role

# Coarser than true role privilege, but adequate here: only ever show an example drawn from a
# role whose table access is a subset of the caller's, so retrieval can't leak a query shape
# over data the caller isn't allowed to see.
_ROLE_RANK: dict[Role, int] = {"anonymous": 0, "viewer": 1, "analyst": 2, "approver": 2, "admin": 2}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def retrieve_examples(
    question: str, role: Role, k: int = 3, golden: list[GoldenQuestion] | None = None
) -> list[GoldenQuestion]:
    """Top-`k` golden questions by token (Jaccard) overlap with `question`, ties broken by id
    for a stable, testable order."""
    pool = golden if golden is not None else load_golden()
    caller_rank = _ROLE_RANK[role]
    candidates = [g for g in pool if g.sql and _ROLE_RANK.get(g.role, 99) <= caller_rank]

    q_tokens = _tokens(question)
    scored: list[tuple[float, str, GoldenQuestion]] = []
    for g in candidates:
        g_tokens = _tokens(g.question)
        union = q_tokens | g_tokens
        overlap = len(q_tokens & g_tokens) / len(union) if union else 0.0
        scored.append((overlap, g.id, g))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [g for _, _, g in scored[:k]]


def format_examples(examples: list[GoldenQuestion]) -> str:
    """Render retrieved examples as the few-shot block the text-to-SQL prompt shows."""
    if not examples:
        return "(no similar examples found)"
    blocks = [f"Q: {g.question}\nSQL: {g.sql}" for g in examples]
    return "\n\n".join(blocks)
