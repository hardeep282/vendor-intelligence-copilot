"""Tokenization lab (Day 3 step 9): compare three ways of counting tokens on this project's
own real prompts -- Anthropic's provider counter (exact, a real API call), `tiktoken`
(a local, offline approximation), and a Hugging Face tokenizer (a different local, offline
approximation) -- then project what each one's count would predict for cost per 1,000
requests at this project's real Sonnet 5 pricing (copilot.llm.pricing.PRICES).

Why this needs your machine, not just an API key: `tiktoken` and the Hugging Face tokenizer
both need a one-time network download (their vocab files) from hosts this project's own build
sandbox cannot reach (openaipublic.blob.core.windows.net and huggingface.co were both behind
this sandbox's proxy allowlist when this script was written -- confirmed by trying, not
assumed). The provider counter additionally needs a real ANTHROPIC_API_KEY. None of that is
unusual for this project's "run it yourself" scripts (see docs/HANDOFF.md), but this one is
the first that needs outbound network access beyond api.anthropic.com -- if your machine also
blocks those two hosts, `tiktoken.get_encoding()` / `Tokenizer.from_pretrained()` will say so.

Cost: `messages.count_tokens(...)` does not generate a completion, so it is billed as a
token-counting request (far cheaper than a real message) -- the 5 real calls this script makes
by default cost a small fraction of one InsightService call.

Usage: uv run python scripts/run_tokenization_lab.py
"""

from __future__ import annotations

import sys

import anthropic

from copilot.data import store
from copilot.evals.golden import GOLDEN_V2_PATH, load_golden
from copilot.evals.tokenization_lab import (
    PromptSample,
    anthropic_provider_counter,
    hf_text_counter,
    load_hf_tokenizer,
    run_tokenization_lab,
    tiktoken_text_counter,
)
from copilot.guardrails.policy import load_policy
from copilot.insights.service import gather_vendor_data
from copilot.llm.prompts import load_prompt
from copilot.settings import get_settings
from copilot.sql.examples import format_examples, retrieve_examples
from copilot.sql.schema import build_schema_card

MODEL = "claude-sonnet-5"


def _anthropic_client() -> anthropic.Anthropic:
    """`anthropic.Anthropic()` with no args only reads a real OS environment variable, not
    `.env` -- `.env` is loaded by `copilot.settings.get_settings()` (pydantic-settings), the
    same place `LLMClient` gets its key from. Go through it so this script works from a plain
    `.env` file instead of requiring the key to also be exported in the shell."""
    key = get_settings().anthropic_api_key
    if key is None:
        print(
            "error: no ANTHROPIC_API_KEY found (checked .env via copilot.settings). "
            "Add it to your .env file -- see docs/HANDOFF.md.",
            file=sys.stderr,
        )
        sys.exit(1)
    return anthropic.Anthropic(api_key=key.get_secret_value())


def _text_to_sql_samples() -> list[PromptSample]:
    """Real system/user text as `TextToSqlService.answer()` actually builds it -- same
    schema_card + retrieved examples a live call would send, for a viewer and an analyst."""
    prompt = load_prompt("text_to_sql")
    policy = load_policy()
    golden = load_golden(GOLDEN_V2_PATH)
    samples = []
    for qid, role in [("gq-001", "viewer"), ("gq-045", "analyst"), ("gq-042", "viewer")]:
        question = next(q.question for q in golden if q.id == qid)
        schema_card = build_schema_card(policy, role)  # type: ignore[arg-type]
        examples_block = format_examples(retrieve_examples(question, role))  # type: ignore[arg-type]
        system = prompt.render_system(
            role=role, schema_card=schema_card, examples_block=examples_block
        )
        samples.append(
            PromptSample(
                label=f"text_to_sql[{role}]: {qid}",
                system=system,
                user_messages=[prompt.render_user(question=question)],
            )
        )
    return samples


def _vendor_insight_sample() -> PromptSample | None:
    """Real system/user text for one vendor_insight call, if the snapshot has one vendor to
    use. Returns None (and the lab just runs on fewer prompts) if the snapshot isn't built."""
    if not (get_settings().snapshot_dir / "MANIFEST.json").exists():
        return None
    import json

    con = store.connect()
    policy = load_policy()
    prompt = load_prompt("vendor_insight")
    row = con.execute("SELECT VendorName FROM vendor_tiering LIMIT 1").fetchone()
    if row is None:
        return None
    vendor_name = row[0]
    data = gather_vendor_data(con, vendor_name, policy, "viewer")
    return PromptSample(
        label=f"vendor_insight[viewer]: {vendor_name}",
        system=prompt.render_system(role="viewer"),
        user_messages=[
            prompt.render_user(
                vendor_name=vendor_name, vendor_data_block=json.dumps(data, indent=2, default=str)
            )
        ],
    )


def main() -> int:
    samples = _text_to_sql_samples()
    extra = _vendor_insight_sample()
    if extra is not None:
        samples.append(extra)

    print(f"Running {len(samples)} prompt(s) through 3 token-counting methods...\n")

    client = _anthropic_client()
    report = run_tokenization_lab(
        samples,
        model=MODEL,
        provider_counter=anthropic_provider_counter(client),
        tiktoken_counter=tiktoken_text_counter(),
        hf_counter=hf_text_counter(load_hf_tokenizer("gpt2")),
    )

    print(f"{'prompt':<32} {'provider':>9} {'tiktoken':>9} {'err%':>7} {'hf':>7} {'err%':>7}")
    for p in report.prompts:
        by_method = {c.method: c for c in p.counts}
        print(
            f"{p.label[:32]:<32} {by_method['provider'].tokens:>9} "
            f"{by_method['tiktoken'].tokens:>9} "
            f"{by_method['tiktoken'].pct_error_vs_provider:>+6.1f}% "
            f"{by_method['hf'].tokens:>7} "
            f"{by_method['hf'].pct_error_vs_provider:>+6.1f}%"
        )

    print(f"\n{'method':<10} {'avg_tokens':>10} {'avg_err%':>9} {'$/1000 req':>11}")
    for s in report.by_method:
        err = (
            f"{s.avg_abs_pct_error_vs_provider:>8.1f}%"
            if s.avg_abs_pct_error_vs_provider is not None
            else f"{'n/a':>9}"
        )
        print(f"{s.method:<10} {s.avg_tokens:>10.1f} {err} ${s.cost_per_1000_requests_usd:>10.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
