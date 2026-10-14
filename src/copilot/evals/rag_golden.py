"""RAG golden set: schema, loader, and the "what's actually relevant" resolver (Day 4 step 7).

Purpose : 20 questions against the real knowledge corpus, each labelled well enough to say
          which chunk(s) are the correct retrieval for it -- without labelling by `chunk_id`
          directly, because a chunk_id is an artefact of the current chunking (heading order,
          `chunk_index`); re-chunk the corpus (a wording edit, a new heading) and every id in
          the dataset would go stale even though the underlying facts didn't change. Instead,
          each question names the document it came from (`doc_type` + optional `vendor`, the
          same metadata every chunk already carries) and a short, verbatim `must_contain`
          phrase unique to the right section -- `relevant_chunk_ids()` resolves that against
          *whatever* chunk list is passed in, at eval time, so the dataset survives a re-chunk.
Inputs  : evals/datasets/rag_golden_v1.jsonl, and the chunk list to resolve relevance against
          (normally `copilot.rag.chunking.chunk_corpus(copilot.rag.corpus.load_corpus())`).
Outputs : typed `RagGoldenQuestion` objects; `relevant_chunk_ids()` returns the resolved set.

Every question's `role` is deliberately a role the disclosure policy already lets see that
question's `data_class` (an `analyst` for confidential vendor-contract questions, a `viewer`
for public/internal ones) -- this dataset measures retrieval quality, not permission
correctness, which `tests/test_rag_permissions.py` already covers directly. Mixing the two
here would make a low recall score ambiguous: is ranking bad, or did the role legitimately
never see the right chunk?
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from copilot.guardrails.policy import DataClass, Role
from copilot.rag.chunking import Chunk
from copilot.rag.corpus import DocType
from copilot.settings import REPO_ROOT

RAG_GOLDEN_PATH = REPO_ROOT / "evals" / "datasets" / "rag_golden_v1.jsonl"


class RagGoldenQuestion(BaseModel):
    id: str
    question: str
    role: Role
    doc_type: DocType | None = None
    vendor: str | None = None
    must_contain: str
    data_class: DataClass


def load_rag_golden(path: Path = RAG_GOLDEN_PATH) -> list[RagGoldenQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RagGoldenQuestion.model_validate_json(line) for line in lines if line.strip()]


def relevant_chunk_ids(question: RagGoldenQuestion, chunks: list[Chunk]) -> set[str]:
    """The chunk(s) in `chunks` that count as a correct retrieval for `question`: matching
    `doc_type`/`vendor` when the question specifies them, and containing `must_contain`
    (case-insensitive). Every question in the shipped dataset resolves to exactly one chunk
    against the real corpus (verified when the dataset was built) -- a different count here
    means either the corpus changed under a question or the question itself needs updating,
    not a retrieval bug.
    """
    return {
        c.chunk_id
        for c in chunks
        if (question.doc_type is None or c.doc_type == question.doc_type)
        and (question.vendor is None or c.vendor == question.vendor)
        and question.must_contain.lower() in c.text.lower()
    }


__all__ = ["RAG_GOLDEN_PATH", "RagGoldenQuestion", "load_rag_golden", "relevant_chunk_ids"]
