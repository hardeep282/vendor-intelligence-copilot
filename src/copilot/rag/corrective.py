"""Corrective RAG loop in LangGraph (Day 4 step 6): retrieve -> grade -> rewrite -> retry ->
abstain.

Purpose : plain retrieval (steps 4-5) returns the best-ranked chunks it has, even when none of
          them actually help -- RRF and the permission filter both rank and restrict, neither
          judges "is this actually useful." Corrective RAG (Yan et al., 2024) adds a grading
          step that can reject a bad retrieval and try again with a better query, instead of
          generating an answer grounded in passages that merely ranked well. The retry budget
          and "abstain rather than guess" posture mirror `copilot.sql.service`'s self-correction
          loop (`MAX_SELF_CORRECTIONS`) -- same philosophy, applied to retrieval instead of SQL
          validation: a bounded number of corrections, then an honest "couldn't find grounding"
          instead of an answer built on weak evidence.
Inputs  : a question, a Role (passed straight through to the PermissionedRetriever underneath,
          so this loop is permission-aware by construction, not by a separate check bolted on).
Outputs : a CorrectiveRagResult -- either a grounded answer citing the chunk ids it actually
          used, or an explicit abstention with the reason, plus cost/latency/call accounting in
          the same shape TextToSqlResult uses.

Simplified from the CRAG paper on purpose: the paper's "Incorrect" grade triggers an external
web search as a fallback knowledge source. This system has no web search (it answers from one
company's internal corpus, by design -- see docs/adr/002), so "not enough relevant passages"
triggers a query rewrite and another pass over the *same* corpus instead of an external
fetch. That's a real simplification, not the full CRAG design, and is logged here rather than
as a new ADR for the same reason the embedding model and vector store weren't: it follows from
a decision (ADR-002, no external fetch of licensed-adjacent data) already made, not a new one.

Three LLM calls make up the loop, each its own versioned prompt (`prompts/crag_grade/`,
`prompts/crag_rewrite/`, `prompts/crag_generate/`) -- grading and rewriting are cheap
classification-ish calls (`effort: low`); generation gets `effort: medium`, same tier as the
other grounded-answer prompts in this repo.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, cast

from anthropic.types import MessageParam
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from copilot.guardrails.canary import canary_line
from copilot.guardrails.policy import Role
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics
from copilot.rag.retrieval import RetrievedChunk

# Mirrors copilot.sql.service.MAX_SELF_CORRECTIONS: the first retrieval attempt plus up to this
# many query-rewrite retries, then abstain rather than answer from ungraded-relevant passages.
MAX_CORRECTIONS = 2

# At least this many chunks must be graded relevant before the loop will generate an answer.
# 1, not a majority-of-the-pool threshold: a single genuinely relevant passage is still real
# grounding, and demanding more would make the loop reject a correct-but-narrow retrieval.
MIN_RELEVANT_CHUNKS = 1

_Route = Literal["generate", "rewrite", "abstain"]


class ChunkGrade(BaseModel):
    chunk_id: str
    relevant: bool


class RetrievalGrade(BaseModel):
    """Forced structured output for the crag_grade prompt."""

    grades: list[ChunkGrade]


class QueryRewrite(BaseModel):
    """Forced structured output for the crag_rewrite prompt."""

    rewritten_query: str
    reasoning: str


class GroundedAnswer(BaseModel):
    """Forced structured output for the crag_generate prompt."""

    answer: str
    cited_chunk_ids: list[str] = []


class CorrectiveRagResult(BaseModel):
    question: str
    role: Role
    answer: str | None = None
    cited_chunk_ids: list[str] = []
    rewritten_queries: list[str] = []
    corrections: int = 0
    abstained: bool
    abstain_reason: str | None = None
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    llm_calls: int = 0


class Retriever(Protocol):
    """Structural type for whatever retriever this loop wraps -- in practice
    `copilot.rag.permissions.PermissionedRetriever`, so this loop is permission-aware by
    construction. A Protocol (not the concrete class) so tests can pass a lightweight stub
    without subclassing the real thing.
    """

    def retrieve(
        self, query: str, role: Role, n_results: int = ..., candidate_pool: int = ...
    ) -> list[RetrievedChunk]: ...


class _State(TypedDict):
    question: str
    role: Role
    query: str
    attempt: int
    retrieved: list[RetrievedChunk]
    relevant_ids: set[str]
    rewritten_queries: list[str]
    total_cost_usd: float
    total_latency_s: float
    llm_calls: int
    result: CorrectiveRagResult | None


def _format_chunks_block(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no passages retrieved)"
    parts = []
    for r in chunks:
        heading = " > ".join(r.chunk.heading_path)
        parts.append(f"[{r.chunk.chunk_id}] ({r.chunk.data_class}) {heading}\n{r.chunk.text}")
    return "\n\n".join(parts)


class CorrectiveRagService:
    """Wraps a Retriever (permission-aware) and an LLMClient in the retrieve/grade/rewrite/
    generate/abstain loop, compiled once as a LangGraph graph in `__init__`.
    """

    def __init__(
        self,
        llm: LLMClient,
        retriever: Retriever,
        n_results: int = 5,
        effort: Effort | None = None,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._n_results = n_results
        self._effort = effort
        self._graph = self._build_graph()

    def answer(self, question: str, role: Role) -> CorrectiveRagResult:
        initial: _State = {
            "question": question,
            "role": role,
            "query": question,
            "attempt": 0,
            "retrieved": [],
            "relevant_ids": set(),
            "rewritten_queries": [],
            "total_cost_usd": 0.0,
            "total_latency_s": 0.0,
            "llm_calls": 0,
            "result": None,
        }
        final_state = cast("_State", self._graph.invoke(initial))
        result = final_state["result"]
        if result is None:
            # Can't happen: every path through the graph (generate, abstain) sets "result"
            # before reaching END. Raised rather than asserted so it survives -O, same as any
            # other "the graph's own contract was violated" condition would deserve.
            raise RuntimeError("corrective RAG graph reached END without producing a result")
        return result

    # -- graph construction --------------------------------------------------------------

    def _build_graph(self) -> Any:  # noqa: ANN401 -- CompiledStateGraph's generic params aren't
        # worth spelling out here; this return value is only ever used via the narrow
        # `.invoke()` call below, immediately `cast` back to `_State`.
        graph: StateGraph[_State] = StateGraph(_State)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("grade", self._grade)
        graph.add_node("rewrite", self._rewrite)
        graph.add_node("generate", self._generate)
        graph.add_node("abstain", self._abstain)
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges(
            "grade",
            self._route_after_grade,
            {"generate": "generate", "rewrite": "rewrite", "abstain": "abstain"},
        )
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("generate", END)
        graph.add_edge("abstain", END)
        return graph.compile()

    # -- nodes -----------------------------------------------------------------------------

    def _retrieve(self, state: _State) -> dict[str, object]:
        retrieved = self._retriever.retrieve(
            state["query"], state["role"], n_results=self._n_results
        )
        return {"retrieved": retrieved}

    def _grade(self, state: _State) -> dict[str, object]:
        retrieved = state["retrieved"]
        if not retrieved:
            # Nothing to grade -- skip the LLM call rather than ask it to grade an empty list.
            return {"relevant_ids": set()}

        prompt = load_prompt("crag_grade")
        system = prompt.render_system(chunks_block=_format_chunks_block(retrieved)) + canary_line(
            "knowledge_grade"
        )
        messages: list[MessageParam] = [
            {"role": "user", "content": prompt.render_user(question=state["question"])}
        ]
        grade, metrics = cast(
            "tuple[RetrievalGrade, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=RetrievalGrade,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            ),
        )
        retrieved_ids = {r.chunk.chunk_id for r in retrieved}
        # Only trust a "relevant" grade for a chunk id that was actually shown -- a graded id
        # outside that set can't have come from a real judgement of the retrieved text.
        relevant_ids = {
            g.chunk_id for g in grade.grades if g.relevant and g.chunk_id in retrieved_ids
        }
        return {
            "relevant_ids": relevant_ids,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _route_after_grade(self, state: _State) -> _Route:
        if len(state["relevant_ids"]) >= MIN_RELEVANT_CHUNKS:
            return "generate"
        if state["attempt"] >= MAX_CORRECTIONS:
            return "abstain"
        return "rewrite"

    def _rewrite(self, state: _State) -> dict[str, object]:
        prompt = load_prompt("crag_rewrite")
        previous = state["rewritten_queries"] or [state["question"]]
        system = prompt.render_system(previous_queries="; ".join(previous)) + canary_line(
            "knowledge_rewrite"
        )
        messages: list[MessageParam] = [
            {"role": "user", "content": prompt.render_user(question=state["question"])}
        ]
        rewrite, metrics = cast(
            "tuple[QueryRewrite, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=QueryRewrite,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            ),
        )
        return {
            "query": rewrite.rewritten_query,
            "attempt": state["attempt"] + 1,
            "rewritten_queries": [*state["rewritten_queries"], rewrite.rewritten_query],
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _generate(self, state: _State) -> dict[str, object]:
        relevant = [r for r in state["retrieved"] if r.chunk.chunk_id in state["relevant_ids"]]
        prompt = load_prompt("crag_generate")
        system = prompt.render_system(chunks_block=_format_chunks_block(relevant)) + canary_line(
            "knowledge_generate"
        )
        messages: list[MessageParam] = [
            {"role": "user", "content": prompt.render_user(question=state["question"])}
        ]
        generation, metrics = cast(
            "tuple[GroundedAnswer, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=GroundedAnswer,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            ),
        )
        shown_ids = {r.chunk.chunk_id for r in relevant}
        # Defensive, same posture as copilot.rag.permissions towards a single enforcement
        # point: never trust a citation the model produced for a chunk it wasn't shown.
        cited = [cid for cid in generation.cited_chunk_ids if cid in shown_ids]
        result = CorrectiveRagResult(
            question=state["question"],
            role=state["role"],
            answer=generation.answer,
            cited_chunk_ids=cited,
            rewritten_queries=state["rewritten_queries"],
            corrections=state["attempt"],
            abstained=False,
            total_cost_usd=state["total_cost_usd"] + metrics.cost_usd,
            total_latency_s=state["total_latency_s"] + metrics.total_latency_s,
            llm_calls=state["llm_calls"] + 1,
        )
        return {
            "result": result,
            "total_cost_usd": result.total_cost_usd,
            "total_latency_s": result.total_latency_s,
            "llm_calls": result.llm_calls,
        }

    def _abstain(self, state: _State) -> dict[str, object]:
        reason = (
            f"no passage graded relevant to this question after {state['attempt']} query rewrite(s)"
            if state["retrieved"] or state["rewritten_queries"]
            else "no passages were retrievable for this question and role"
        )
        result = CorrectiveRagResult(
            question=state["question"],
            role=state["role"],
            rewritten_queries=state["rewritten_queries"],
            corrections=state["attempt"],
            abstained=True,
            abstain_reason=reason,
            total_cost_usd=state["total_cost_usd"],
            total_latency_s=state["total_latency_s"],
            llm_calls=state["llm_calls"],
        )
        return {"result": result}
