"""copilot.evals.tokenization_lab: against fakes, no network call and no API key.

The HF "tokenizer" used here is a tiny WordLevel vocabulary built in-process with the real
`tokenizers` library (no download, no network) -- it exercises the same `.encode(text).ids`
interface `hf_text_counter()` calls, which is all this module depends on from a real
pretrained tokenizer. The provider counter is a plain fake standing in for
`client.messages.count_tokens(...)`.
"""

from __future__ import annotations

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from copilot.evals.tokenization_lab import (
    PromptSample,
    hf_text_counter,
    run_tokenization_lab,
    tokenize_prompt,
)


def _tiny_hf_tokenizer() -> Tokenizer:
    words = "the quick brown fox vendor revenue margin select from where role schema".split()
    vocab = {"[UNK]": 0, **{w: i for i, w in enumerate(sorted(set(words)), start=1)}}
    tok = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))  # noqa: S106
    tok.pre_tokenizer = Whitespace()  # type: ignore[assignment]
    return tok


def _fake_provider_counter(tokens_per_call: int):  # type: ignore[no-untyped-def]
    calls: list[dict] = []  # type: ignore[type-arg]

    def _count(*, model: str, system: str, user_messages):  # type: ignore[no-untyped-def]
        calls.append({"model": model, "system": system, "user_messages": list(user_messages)})
        return tokens_per_call

    _count.calls = calls  # type: ignore[attr-defined]
    return _count


def _tiktoken_stub(text: str) -> int:
    # A whitespace-split stand-in: real tiktoken needs a one-time network download of its BPE
    # vocab (blocked from this project's own build sandbox, same as the HF download below --
    # both run for real on `scripts/run_tokenization_lab.py`'s machine, not in these tests).
    return len(text.split())


def test_tokenize_prompt_reports_provider_as_ground_truth_with_no_error() -> None:
    sample = PromptSample(
        label="lookup", system="You are a helper for role {role}.", user_messages=["hello"]
    )
    provider = _fake_provider_counter(42)

    result = tokenize_prompt(
        sample,
        model="claude-sonnet-5",
        provider_counter=provider,
        tiktoken_counter=_tiktoken_stub,
        hf_counter=hf_text_counter(_tiny_hf_tokenizer()),
    )

    by_method = {c.method: c for c in result.counts}
    assert by_method["provider"].tokens == 42
    assert by_method["provider"].pct_error_vs_provider is None
    assert by_method["tiktoken"].pct_error_vs_provider is not None
    assert by_method["hf"].pct_error_vs_provider is not None


def test_approximation_error_is_signed_and_matches_arithmetic() -> None:
    sample = PromptSample(label="x", system="vendor revenue margin", user_messages=[])
    provider = _fake_provider_counter(10)  # tiktoken_stub on "vendor revenue margin" -> 3 tokens

    result = tokenize_prompt(
        sample,
        model="claude-sonnet-5",
        provider_counter=provider,
        tiktoken_counter=_tiktoken_stub,
        hf_counter=lambda _t: 10,
    )

    by_method = {c.method: c for c in result.counts}
    # (3 - 10) / 10 * 100 = -70.0
    assert by_method["tiktoken"].tokens == 3
    assert by_method["tiktoken"].pct_error_vs_provider == pytest.approx(-70.0)
    # hf matches the provider exactly here -> 0% error
    assert by_method["hf"].tokens == 10
    assert by_method["hf"].pct_error_vs_provider == pytest.approx(0.0)


def test_provider_counter_receives_the_real_system_and_user_text() -> None:
    sample = PromptSample(label="x", system="SYSTEM TEXT", user_messages=["Q1", "Q2"])
    provider = _fake_provider_counter(5)

    tokenize_prompt(
        sample,
        model="claude-sonnet-5",
        provider_counter=provider,
        tiktoken_counter=_tiktoken_stub,
        hf_counter=lambda _t: 5,
    )

    assert provider.calls == [  # type: ignore[attr-defined]
        {"model": "claude-sonnet-5", "system": "SYSTEM TEXT", "user_messages": ["Q1", "Q2"]}
    ]


def test_lab_summarizes_avg_tokens_error_and_cost_per_1000_requests() -> None:
    samples = [
        PromptSample(label="a", system="vendor revenue margin", user_messages=[]),
        PromptSample(label="b", system="select from where role schema", user_messages=[]),
    ]
    provider = _fake_provider_counter(100)

    report = run_tokenization_lab(
        samples,
        model="claude-sonnet-5",
        provider_counter=provider,
        tiktoken_counter=_tiktoken_stub,
        hf_counter=hf_text_counter(_tiny_hf_tokenizer()),
    )

    assert len(report.prompts) == 2
    by_method = {m.method: m for m in report.by_method}
    assert by_method["provider"].avg_tokens == 100.0
    assert by_method["provider"].avg_abs_pct_error_vs_provider is None
    assert by_method["tiktoken"].avg_abs_pct_error_vs_provider is not None
    # Every method's cost projection uses the real Sonnet 5 pricing table, so a wildly wrong
    # token count (tiktoken/hf here, both far under 100) shows up as a cheaper-looking estimate.
    assert (
        by_method["tiktoken"].cost_per_1000_requests_usd
        < by_method["provider"].cost_per_1000_requests_usd
    )


def test_run_with_no_samples_produces_no_summary_rows() -> None:
    report = run_tokenization_lab(
        [],
        model="claude-sonnet-5",
        provider_counter=_fake_provider_counter(1),
        tiktoken_counter=_tiktoken_stub,
        hf_counter=lambda _t: 1,
    )
    assert report.prompts == []
    assert report.by_method == []
