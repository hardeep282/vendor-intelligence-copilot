"""copilot.llm.pricing: cost arithmetic must be exact and must never silently default to $0."""

import pytest

from copilot.llm.pricing import PRICES, UnknownModelError, cost_usd


def test_known_model_cost_is_exact() -> None:
    # 1,000,000 input + 1,000,000 output tokens on Haiku 5.5 = $0.10 + $0.50 exactly.
    got = cost_usd("claude-haiku-5-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert got == pytest.approx(0.60)


def test_cache_read_is_cheaper_than_input() -> None:
    price = PRICES["claude-sonnet-5"]
    assert price.cache_read < price.input


def test_cache_tokens_are_priced_separately() -> None:
    base = cost_usd("claude-sonnet-5", input_tokens=1000, output_tokens=0)
    with_cache_read = cost_usd(
        "claude-sonnet-5", input_tokens=1000, output_tokens=0, cache_read_tokens=1000
    )
    assert with_cache_read > base  # cache-read tokens are billed in addition to input tokens


def test_unknown_model_raises_instead_of_returning_zero() -> None:
    with pytest.raises(UnknownModelError):
        cost_usd("claude-made-up-model", input_tokens=10, output_tokens=10)
