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


class LLMResult(BaseModel):
    """What copilot.llm.client.LLMClient.complete() returns."""

    text: str
    metrics: CallMetrics


class LLMCallError(RuntimeError):
    """Raised when the client gives up after retries, or a tool call is malformed."""


class StructuredOutputError(LLMCallError):
    """Raised when structured() exhausts its repair retries without valid output."""
