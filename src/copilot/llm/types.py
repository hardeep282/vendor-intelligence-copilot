"""Typed results from the LLM client.

Purpose : every call returns the same shape, so logging, LangSmith and tests never have to
          branch on which call path produced it.
Inputs  : none (populated by copilot.llm.client).
Outputs : CallMetrics (the numbers an interviewer will ask about: TTFT, latency, tokens, cost).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CallMetrics(BaseModel):
    """Per-call instrumentation. Logged for every LLM call, never silently dropped."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float
    ttft_s: float = Field(description="Time to first streamed token/event, seconds.")
    total_latency_s: float = Field(description="Wall-clock time for the whole call, seconds.")
    stop_reason: str | None = None
    attempt: int = Field(default=1, description="1 = first try; >1 = a tenacity retry succeeded.")
    repair_attempt: int = Field(
        default=0, description="0 = no repair needed; >0 = structured() self-corrected."
    )
    # Day 8, Addendum A2 §1.5 (version pinning): which versioned prompts/<name>/v<N>.yaml file
    # produced this call's system/user text, if the caller loaded one via `copilot.llm.prompts`.
    # `None` for a call that built its own messages directly (no versioned prompt involved) --
    # every live call site in this project does load one, so in practice this is set everywhere
    # it matters. Carried on `CallMetrics` (not a separate parameter) specifically so it reaches
    # every trace automatically: `LLMClient.complete`/`.structured` are `@traceable`-decorated
    # with `process_outputs=mask_run_payload`, which serializes the return value LangSmith
    # stores -- a field on the thing already being traced needs no extra wiring to show up
    # there, and it is equally available wherever an eval harness logs a `CallMetrics` row.
    prompt_name: str | None = None
    prompt_version: int | None = None
    # Day 8, Addendum A2 §1.1 (fallback model): set when the configured primary model exhausted
    # its retries and this result actually came from the configured fallback instead. `model`
    # above is already the model that *produced* the result (the fallback's id when this is
    # True) -- this flag is what a trace/eval row needs to tell "fallback succeeded" apart from
    # "primary succeeded on the first try", since both would otherwise look identical.
    used_fallback_model: bool = False


class LLMResult(BaseModel):
    """What copilot.llm.client.LLMClient.complete() returns."""

    text: str
    metrics: CallMetrics


class LLMCallError(RuntimeError):
    """Raised when the client gives up after retries, or a tool call is malformed."""


class StructuredOutputError(LLMCallError):
    """Raised when structured() exhausts its repair retries without valid output."""
