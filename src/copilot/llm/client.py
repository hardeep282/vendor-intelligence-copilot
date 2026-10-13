"""LLM client wrapper around the Anthropic Messages API.

Purpose : the one place every agent and service calls an LLM through, so retries, timeouts,
          prompt caching, tracing and per-call cost/latency logging are never re-implemented
          per caller. This is the B1 "baseline every later phase must beat".
Inputs  : model id, system prompt, messages, and (for structured()) a Pydantic output model.
Outputs : LLMResult / a validated Pydantic instance, each paired with a CallMetrics row.

API surface verified against the installed SDK (anthropic==1.13.0, checked 14 Oct 2026) --
this corrects the sprint plan's assumption that `temperature` still works the old way:

  - **`temperature`, `top_p` and `top_k` are gone from this model generation's Messages API.**
    They are not even parameters of `client.messages.create()` / `.stream()` in this SDK
    version, and Anthropic's Sonnet 5.5 migration guide confirms a non-default value on these
    now returns a 400 ("Remove them"). The replacement sampling-adjacent control is
    `output_config.effort` (`low` / `medium` / `high` / `xhigh` / `max`), which trades
    reasoning depth for latency/cost -- it is not a temperature substitute, but it is the one
    per-call knob this generation exposes, so Day 3's "temperature lab" is rebuilt as an
    **effort lab** (B1 step 8): same question, `effort` swept instead of `temperature`,
    same metrics (execution accuracy / grounding / output diversity / latency / cost).
  - `client.messages.stream(..., output_format=SomePydanticModel)` both streams (for TTFT) and
    parses the final text block into that model via `ParsedMessage.content[0].parsed_output`.
  - Prompt caching is a `cache_control={"type": "ephemeral"}` block on a system TextBlockParam.
  - Retryable exceptions: RateLimitError, (API)ConnectionError, (API)TimeoutError,
    InternalServerError, ServiceUnavailableError, OverloadedError, DeadlineExceededError.
    `max_retries=0` is passed to the SDK client so *we* control backoff, jitter and logging
    (tenacity), instead of the SDK silently retrying underneath us.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from typing import Any, Literal, TypeVar, cast

import anthropic
from anthropic.types import MessageParam, TextBlockParam
from langsmith import traceable
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from copilot.llm.pricing import cost_usd
from copilot.llm.types import CallMetrics, LLMCallError, LLMResult, StructuredOutputError
from copilot.settings import get_settings

log = logging.getLogger("copilot.llm")

T = TypeVar("T", bound=BaseModel)

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Errors worth retrying: transient network/server conditions, not bad requests or bad auth.
_RETRYABLE: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.ServiceUnavailableError,
    anthropic.OverloadedError,
    anthropic.DeadlineExceededError,
)


def _retrying() -> Any:
    """A fresh tenacity decorator per call, so `attempt` numbers never leak between calls."""
    return retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_random_exponential(multiplier=1, max=20),  # backoff + jitter
        stop=stop_after_attempt(4),  # 1 try + up to 3 retries
        reraise=True,
    )


def _system_blocks(system: str, cache: bool) -> list[TextBlockParam]:
    """One text block, cached (prompt caching) when the caller says the system prompt is stable."""
    block: TextBlockParam = {"type": "text", "text": system}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _metrics_from_usage(
    model: str,
    usage: Any,
    ttft: float | None,
    total: float,
    stop_reason: str | None,
    attempt: int,
    repair_attempt: int = 0,
) -> CallMetrics:
    return CallMetrics(
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cost_usd=cost_usd(
            model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_creation_input_tokens or 0,
            usage.cache_read_input_tokens or 0,
        ),
        ttft_s=ttft if ttft is not None else total,
        total_latency_s=total,
        stop_reason=stop_reason,
        attempt=attempt,
        repair_attempt=repair_attempt,
    )


class LLMClient:
    """Thin, instrumented wrapper over `anthropic.Anthropic`. One instance per process is fine."""

    def __init__(self, api_key: str | None = None, timeout_s: float = 60.0) -> None:
        settings_key = get_settings().anthropic_api_key
        key = api_key or (settings_key.get_secret_value() if settings_key is not None else None)
        if not key:
            raise LLMCallError(
                "no Anthropic API key: set ANTHROPIC_API_KEY in .env (dev keys only; "
                "see ADR-004 and docs/HANDOFF.md -- keys never go in chat)"
            )
        # max_retries=0: tenacity below owns retry/backoff so every attempt is logged and costed.
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout_s, max_retries=0)
        self._configure_tracing()

    @staticmethod
    def _configure_tracing() -> None:
        """Export LangSmith's own env vars from our settings, so `@traceable` picks them up
        without the caller having to `export` anything by hand (dev tracing project by default).
        """
        s = get_settings()
        if s.langsmith_tracing and s.langsmith_api_key:
            os.environ.setdefault("LANGSMITH_TRACING", "true")
            os.environ.setdefault("LANGSMITH_API_KEY", s.langsmith_api_key.get_secret_value())
            os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)

    @traceable(run_type="llm", name="LLMClient.complete")
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[MessageParam],
        max_tokens: int,
        effort: Effort | None = None,
        cache_system: bool = False,
    ) -> LLMResult:
        """Plain text completion. Streams internally so TTFT is measured, not estimated.

        No `temperature`: this model generation's API does not accept it (see module docstring).
        `effort` is this generation's nearest per-call lever and is optional.
        """
        attempt_count = 0

        @_retrying()  # type: ignore[untyped-decorator]
        def _call() -> LLMResult:
            nonlocal attempt_count
            attempt_count += 1
            t0 = time.monotonic()
            ttft: float | None = None
            kwargs: dict[str, Any] = {}
            if effort is not None:
                kwargs["output_config"] = {"effort": effort}
            with self._client.messages.stream(
                model=model,
                system=_system_blocks(system, cache_system),
                messages=list(messages),
                max_tokens=max_tokens,
                **kwargs,
            ) as stream:
                for event in stream:
                    if ttft is None and event.type == "content_block_delta":
                        ttft = time.monotonic() - t0
                final = stream.get_final_message()
            total = time.monotonic() - t0
            metrics = _metrics_from_usage(
                model, final.usage, ttft, total, final.stop_reason, attempt_count
            )
            text = "".join(b.text for b in final.content if b.type == "text")
            log.info(
                "llm.complete model=%s attempt=%d ttft=%.3fs total=%.3fs tokens_in=%d "
                "tokens_out=%d cache_read=%d cost_usd=%.5f stop=%s",
                model,
                attempt_count,
                metrics.ttft_s,
                metrics.total_latency_s,
                metrics.input_tokens,
                metrics.output_tokens,
                metrics.cache_read_tokens,
                metrics.cost_usd,
                metrics.stop_reason,
            )
            return LLMResult(text=text, metrics=metrics)

        return cast(LLMResult, _call())

    @traceable(run_type="llm", name="LLMClient.structured")
    def structured(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[MessageParam],
        output_model: type[T],
        max_tokens: int,
        effort: Effort | None = None,
        cache_system: bool = False,
        max_repairs: int = 1,
    ) -> tuple[T, CallMetrics]:
        """Forced structured output via the SDK's native `output_format`, with one repair loop.

        A repair loop matters because a model can emit JSON that satisfies the API's schema
        check but still fails *our* stricter Pydantic validators (business rules, enums with
        extra checks) -- `output_format` guarantees shape, not business-rule validity.
        """
        convo: list[MessageParam] = list(messages)
        last_error: Exception | None = None

        for repair_attempt in range(max_repairs + 1):
            attempt_count = 0

            @_retrying()  # type: ignore[untyped-decorator]
            def _call(
                _convo: list[MessageParam] = convo, _repair: int = repair_attempt
            ) -> tuple[T, CallMetrics]:
                nonlocal attempt_count
                attempt_count += 1
                t0 = time.monotonic()
                ttft: float | None = None
                kwargs: dict[str, Any] = {}
                if effort is not None:
                    kwargs["output_config"] = {"effort": effort}
                with self._client.messages.stream(
                    model=model,
                    system=_system_blocks(system, cache_system),
                    messages=_convo,
                    max_tokens=max_tokens,
                    output_format=output_model,
                    **kwargs,
                ) as stream:
                    for event in stream:
                        if ttft is None and event.type == "content_block_delta":
                            ttft = time.monotonic() - t0
                    final = stream.get_final_message()
                total = time.monotonic() - t0
                metrics = _metrics_from_usage(
                    model,
                    final.usage,
                    ttft,
                    total,
                    final.stop_reason,
                    attempt_count,
                    _repair,
                )
                parsed = next(
                    (
                        b.parsed_output
                        for b in final.content
                        if b.type == "text" and b.parsed_output
                    ),
                    None,
                )
                if parsed is None:
                    raise StructuredOutputError(
                        f"model did not return a parseable {output_model.__name__} "
                        f"(stop_reason={final.stop_reason})"
                    )
                # Re-validate through our own model in case the SDK's TypeAdapter and our
                # model's stricter validators (if any were added later) diverge.
                validated = output_model.model_validate(
                    parsed.model_dump() if isinstance(parsed, BaseModel) else parsed
                )
                log.info(
                    "llm.structured model=%s output=%s attempt=%d repair=%d ttft=%.3fs "
                    "total=%.3fs tokens_in=%d tokens_out=%d cost_usd=%.5f",
                    model,
                    output_model.__name__,
                    attempt_count,
                    _repair,
                    metrics.ttft_s,
                    metrics.total_latency_s,
                    metrics.input_tokens,
                    metrics.output_tokens,
                    metrics.cost_usd,
                )
                return validated, metrics

            try:
                return cast("tuple[T, CallMetrics]", _call())
            except (ValidationError, StructuredOutputError) as exc:
                last_error = exc
                if repair_attempt >= max_repairs:
                    break
                log.warning(
                    "llm.structured repair %d/%d after validation failure: %s",
                    repair_attempt + 1,
                    max_repairs,
                    exc,
                )
                convo = [
                    *convo,
                    {"role": "assistant", "content": str(exc)[:500]},
                    {
                        "role": "user",
                        "content": (
                            f"That did not validate against the required schema: {exc}\n"
                            "Return corrected output matching the schema exactly."
                        ),
                    },
                ]

        raise StructuredOutputError(
            f"gave up after {max_repairs} repair attempt(s) producing {output_model.__name__}"
        ) from last_error


__all__ = ["Effort", "LLMClient", "MessageParam"]
