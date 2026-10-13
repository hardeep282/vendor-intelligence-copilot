"""Anthropic API pricing table and cost calculation.

Purpose : turn a call's token counts into a USD figure, so every LLM call can be cost-logged
          without a human doing the arithmetic. One source of truth for prices, so a provider
          price change is a one-line diff here instead of a search-and-replace across the repo.
Inputs  : a model ID string and token counts (input, output, cache write, cache read).
Outputs : cost_usd(...) -> float.

Source  : https://platform.claude.com/docs/en/about-claude/pricing (checked 14 Oct 2026).
          Prices are USD per million tokens. Haiku 5.5 is billed at a higher tier once the
          prompt (including cache reads/writes) exceeds 100K tokens; we assume the lower tier
          here since this project's prompts stay well under that.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens for one model."""

    input: float
    output: float
    cache_write_5m: float
    cache_read: float


# Models this project actually uses. Add a row here before using a new model ID.
PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5": ModelPrice(input=2.0, output=10.0, cache_write_5m=2.50, cache_read=0.20),
    "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_write_5m=0.125, cache_read=0.01),
    "claude-opus-5-5": ModelPrice(input=4.0, output=20.0, cache_write_5m=5.0, cache_read=0.20),
}


class UnknownModelError(ValueError):
    """Raised when asked to price a model not in the PRICES table."""


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """USD cost of one call. Raises UnknownModelError for an unpriced model (fail loud, not $0)."""
    price = PRICES.get(model)
    if price is None:
        raise UnknownModelError(
            f"no price on file for model {model!r}; add it to copilot.llm.pricing.PRICES"
        )
    return (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_write_tokens * price.cache_write_5m
        + cache_read_tokens * price.cache_read
    ) / 1_000_000
