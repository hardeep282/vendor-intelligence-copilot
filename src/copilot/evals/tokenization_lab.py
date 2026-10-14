"""Tokenization lab (Day 3 step 9): provider counter vs. tiktoken vs. a Hugging Face
tokenizer, on real prompts this project actually sends, projected to cost per 1,000 requests.

Why this matters: `copilot.llm.pricing.cost_usd()` prices a call from `usage.input_tokens` /
`usage.output_tokens` that the Anthropic API itself returns after the call -- that figure is
always exact. Before a call happens (budgeting, choosing what to put in a prompt, estimating a
batch job's cost), the only exact count comes from Anthropic's own token-counting endpoint
(`client.messages.count_tokens(...)`), a real, free, authenticated API call. Anthropic has not
published its tokenizer, so two common *local, free, offline* approximations are the fallback
when a budgeting estimate has to happen without a network call: OpenAI's `tiktoken` BPE
encodings, and a Hugging Face `tokenizers.Tokenizer` (a different vocabulary trained for a
different model family). Both are approximations of a tokenizer neither one actually is --
this lab measures how far off each one runs on this project's own prompts, rather than
assuming "a BPE tokenizer is a BPE tokenizer."

Inputs  : one or more `PromptSample`s (label + system text + user messages) and three
          injectable counters -- a `ProviderCounter` (real API call), a local `tiktoken`
          encoding name, and a local HF `Tokenizer` instance. Tests inject fakes/local
          tokenizers for all three; `scripts/run_tokenization_lab.py` builds the real ones.
Outputs : a `TokenizationLabReport` -- per-prompt counts from all three methods, each
          approximation's signed % error against the provider count (ground truth), and a
          cost-per-1,000-requests projection per method so a wrong token count's dollar impact
          is visible, not just its token-count impact.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from copilot.llm.pricing import cost_usd

if TYPE_CHECKING:
    import anthropic
    from tokenizers import Tokenizer

# A representative output size for the cost-per-1,000-requests projection: this project's
# structured SQL-generation outputs run small (a query string + a short assumptions list).
_ASSUMED_OUTPUT_TOKENS = 150


class PromptSample(BaseModel):
    """One real prompt this project sends, flattened to the text each counter needs."""

    label: str
    system: str
    user_messages: list[str]

    @property
    def full_text(self) -> str:
        """System + user turns, concatenated -- what a local, text-only tokenizer counts."""
        return self.system + "\n" + "\n".join(self.user_messages)


class ProviderCounter(Protocol):
    """Anthropic's real token-counting endpoint, or a fake standing in for it in tests."""

    def __call__(self, *, model: str, system: str, user_messages: Sequence[str]) -> int: ...


TextCounter = Callable[[str], int]


class TokenCount(BaseModel):
    method: str
    tokens: int
    pct_error_vs_provider: float | None = None  # None for the provider row itself


class PromptTokenization(BaseModel):
    label: str
    counts: list[TokenCount]


class MethodSummary(BaseModel):
    method: str
    avg_tokens: float
    avg_abs_pct_error_vs_provider: float | None = None  # None for the provider row itself
    cost_per_1000_requests_usd: float


class TokenizationLabReport(BaseModel):
    model: str
    prompts: list[PromptTokenization]
    by_method: list[MethodSummary]


def _pct_error(approx: int, truth: int) -> float | None:
    if truth == 0:
        return None
    return (approx - truth) / truth * 100.0


def tokenize_prompt(
    sample: PromptSample,
    *,
    model: str,
    provider_counter: ProviderCounter,
    tiktoken_counter: TextCounter,
    hf_counter: TextCounter,
) -> PromptTokenization:
    """Count one prompt's tokens all three ways and score the two approximations against
    the provider's real count."""
    provider_tokens = provider_counter(
        model=model, system=sample.system, user_messages=sample.user_messages
    )
    tiktoken_tokens = tiktoken_counter(sample.full_text)
    hf_tokens = hf_counter(sample.full_text)

    return PromptTokenization(
        label=sample.label,
        counts=[
            TokenCount(method="provider", tokens=provider_tokens),
            TokenCount(
                method="tiktoken",
                tokens=tiktoken_tokens,
                pct_error_vs_provider=_pct_error(tiktoken_tokens, provider_tokens),
            ),
            TokenCount(
                method="hf",
                tokens=hf_tokens,
                pct_error_vs_provider=_pct_error(hf_tokens, provider_tokens),
            ),
        ],
    )


def run_tokenization_lab(
    samples: list[PromptSample],
    *,
    model: str,
    provider_counter: ProviderCounter,
    tiktoken_counter: TextCounter,
    hf_counter: TextCounter,
) -> TokenizationLabReport:
    """Tokenize every sample with all three methods, then summarize per method: average
    token count, average absolute % error against the provider (None for the provider row
    itself -- it has nothing to be measured against), and the cost-per-1,000-requests that
    count would project at this project's real Sonnet 5 pricing."""
    prompts = [
        tokenize_prompt(
            s,
            model=model,
            provider_counter=provider_counter,
            tiktoken_counter=tiktoken_counter,
            hf_counter=hf_counter,
        )
        for s in samples
    ]

    by_method: list[MethodSummary] = []
    for method in ("provider", "tiktoken", "hf"):
        rows = [c for p in prompts for c in p.counts if c.method == method]
        n = len(rows)
        if n == 0:
            continue
        avg_tokens = sum(r.tokens for r in rows) / n
        errors = [r.pct_error_vs_provider for r in rows if r.pct_error_vs_provider is not None]
        avg_abs_err = sum(abs(e) for e in errors) / len(errors) if errors else None
        avg_cost = cost_usd(model, int(round(avg_tokens)), _ASSUMED_OUTPUT_TOKENS)
        by_method.append(
            MethodSummary(
                method=method,
                avg_tokens=avg_tokens,
                avg_abs_pct_error_vs_provider=avg_abs_err,
                cost_per_1000_requests_usd=avg_cost * 1000,
            )
        )

    return TokenizationLabReport(model=model, prompts=prompts, by_method=by_method)


# -- real adapters (network/local-model calls; swapped for fakes in tests) ---------------------


def anthropic_provider_counter(client: anthropic.Anthropic) -> ProviderCounter:
    """Wraps `client.messages.count_tokens(...)` -- a real, authenticated API call (no
    completion is generated, so it is billed as a token-counting request, not a message)."""

    def _count(*, model: str, system: str, user_messages: Sequence[str]) -> int:
        result = client.messages.count_tokens(
            model=model,
            system=system,
            messages=[{"role": "user", "content": text} for text in user_messages],
        )
        return result.input_tokens

    return _count


def tiktoken_text_counter(encoding_name: str = "cl100k_base") -> TextCounter:
    """A local, offline approximation using OpenAI's BPE encodings -- not Anthropic's
    tokenizer (Anthropic has not published one), hence this lab scoring it against the
    provider's real count instead of trusting it."""
    import tiktoken

    encoding = tiktoken.get_encoding(encoding_name)
    return lambda text: len(encoding.encode(text))


def hf_text_counter(tokenizer: Tokenizer) -> TextCounter:
    """A local, offline approximation using a Hugging Face `tokenizers.Tokenizer` -- a
    different vocabulary again, trained for a different model family, not Anthropic's."""
    return lambda text: len(tokenizer.encode(text).ids)


def load_hf_tokenizer(name: str = "gpt2") -> Tokenizer:
    """Downloads and caches a pretrained HF tokenizer by name. Needs network access to
    huggingface.co the first time (not available from this project's own build sandbox --
    run this on a machine with normal internet access, same as the other real-call scripts)."""
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(name)
