"""Learning script for session 4: the LLM layer (the one door every Claude call goes through).

Purpose : run the real `LLMClient`, prompt registry and pricing code in eight small, numbered
          steps, so you can watch what a call to Claude is made of in VS Code's debugger.
          **No real Claude call is made.** Claude is replaced by the same scripted stand-in the
          tests use (`tests/fakes/anthropic_fakes.py`), so it's free, needs no key, and gives
          the same output every time. Everything else (building the request, retries set-up,
          validation, the repair loop, cost maths) is the real code.
Inputs  : prompts/ (in the repo). No snapshot needed.
Outputs : plain-English printout of each step. Nothing is written anywhere.

How to use it in VS Code (see the Code Trail page, chapter 4): put a red dot on the first line
inside any `step_...` function, press F5, pick "Python Debugger: Current File", then F10 / F11.
Or just run it:
    uv run python scripts/learn/session4_llm_layer.py

Added 10 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import json
import sys

from anthropic import transform_schema
from pydantic import BaseModel

from copilot.agents.orchestrator import OrchestratorPlan
from copilot.cli import use_utf8_output
from copilot.llm import client as client_module
from copilot.llm.client import LLMClient
from copilot.llm.pricing import PRICES, cost_usd
from copilot.llm.prompts import PROMPTS_DIR, load_prompt
from copilot.rag.corrective import RetrievalGrade
from copilot.settings import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))  # so the tests' Claude stand-in can be imported
from tests.fakes.anthropic_fakes import (  # noqa: E402
    FakeMessagesResource,
    structured_response,
)


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def fake_claude(responses: list[object]) -> tuple[LLMClient, FakeMessagesResource]:
    """A real LLMClient whose network side is swapped for a scripted stand-in."""
    llm = LLMClient(api_key="sk-test-not-real")  # a made-up key; nothing is ever sent
    fake = FakeMessagesResource(responses)  # type: ignore[arg-type]
    llm._client.messages = fake  # type: ignore[misc,assignment]
    return llm, fake


def step_1_versioned_prompts() -> None:
    """Every prompt is a file: prompts/<name>/v<N>.yaml. A change is a new version."""
    heading(1, "The prompt files: one folder per prompt, one file per version")
    for folder in sorted(p for p in PROMPTS_DIR.iterdir() if p.is_dir()):
        latest = load_prompt(folder.name)
        versions = sorted(int(f.stem[1:]) for f in folder.glob("v*.yaml"))
        print(
            f"  {latest.name:<26} v{','.join(map(str, versions)):<8} "
            f"effort {latest.effort or '-':<7} max_tokens {latest.max_tokens:>5}"
        )
    print("\n  The orchestrator's three prompts are on v4: each fix was a new file, so")
    print("  every run's trace records exactly which version produced it.")


def step_2_what_a_call_sends() -> None:
    """Build one real request (the Corrective RAG grader) and look at what would be sent."""
    heading(2, "The 'letter': what one structured call actually sends")
    prompt = load_prompt("crag_grade")
    llm, fake = fake_claude(
        [structured_response({"grades": [{"chunk_id": "c1", "relevant": True}]})]
    )
    grade, metrics = llm.structured(
        model=prompt.model,
        system=prompt.system,
        messages=[{"role": "user", "content": "Question: ... Passages: [c1] ..."}],
        output_model=RetrievalGrade,
        max_tokens=prompt.max_tokens,
        effort=prompt.effort,
        cache_system=prompt.cache_system,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
    )
    sent = fake.calls[0]
    print(f"  model          {sent['model']}")
    print(f"  max_tokens     {sent['max_tokens']}  (the reply's word limit, in tokens)")
    print(f"  output_config  {sent.get('output_config')}  (effort; no temperature exists)")
    print(f"  output_format  {sent['output_format'].__name__}  (the reply's required shape)")
    print(f"  system         {len(sent['system'][0]['text']):,} characters of instructions")
    print(f"  messages       {len(sent['messages'])} (the question and the passages)")
    print(f"\n  reply, already checked against the shape: {grade}")
    print(
        f"  logged with it: prompt {metrics.prompt_name} v{metrics.prompt_version}, "
        f"attempt {metrics.attempt}, {metrics.input_tokens} tokens in, "
        f"{metrics.output_tokens} out, ${metrics.cost_usd:.6f}"
    )
    print("  (the token counts are the stand-in's made-up 100 and 20, not a real reply's)")


def step_3_what_it_costs() -> None:
    """The pricing table turns token counts into dollars (llm/pricing.py)."""
    heading(3, "Cost: the same call priced on each model")
    tokens_in, tokens_out = 3_000, 400
    for model, price in PRICES.items():
        cost = cost_usd(model, tokens_in, tokens_out)
        print(
            f"  {model:<18} ${price.input:>5.2f} in / ${price.output:>5.2f} out per million"
            f"  -> ${cost:.4f}"
        )
    cached = cost_usd("claude-sonnet-5", 200, tokens_out, cache_read_tokens=2_800)
    print(f"\n  Sonnet with 2,800 of the 3,000 input tokens read from the cache: ${cached:.4f}")
    print("  (prompt caching: a long, unchanging system prompt is billed at a tenth on reuse)")


def step_4_what_is_retried() -> None:
    """Which failures are worth trying again, and how often."""
    heading(4, "Retries: which errors are retried, and which aren't")
    for exc in client_module._RETRYABLE:
        print(f"  retried: {exc.__name__}")
    print("\n  Up to 4 tries in all, waiting a random, growing time between them (max 20 s).")
    print("  A bad request or a bad key is never retried: trying again can't fix it.")


def step_5_the_repair_loop() -> None:
    """The reply's shape is right but a value fails our own check: ask once more."""
    heading(5, "The repair loop: a reply that doesn't validate gets one second chance")
    llm, fake = fake_claude(
        [
            structured_response({"grades": [{"chunk_id": "c1"}]}),  # 'relevant' missing
            structured_response({"grades": [{"chunk_id": "c1", "relevant": False}]}),
        ]
    )
    grade, metrics = llm.structured(
        model="claude-sonnet-5",
        system="Grade each passage.",
        messages=[{"role": "user", "content": "..."}],
        output_model=RetrievalGrade,
        max_tokens=200,
    )
    print("  1st reply: {'grades': [{'chunk_id': 'c1'}]}   -> fails: 'relevant' is missing")
    print(f"  2nd reply: {grade}  -> accepted")
    print(f"  calls made: {len(fake.calls)}; repair_attempt logged = {metrics.repair_attempt}")
    last = fake.calls[1]["messages"][-1]["content"]
    print(f"  what the 2nd call was told: {last.splitlines()[0][:70]}...")


class _OldPlanTask(BaseModel):
    """How a plan task looked before 2 Nov: constraints as an open dictionary."""

    agent: str
    constraints: dict[str, str]


def step_6_the_empty_box_bug() -> None:
    """The structured-output bug that hid for a week (fixed 2 Nov)."""
    heading(6, "The empty-box bug: what the API is really told the shape is")
    old = transform_schema(_OldPlanTask)["properties"]["constraints"]
    print(f"  before (dict[str, str]):  {json.dumps(old)}")
    print("    an object with no named fields and nothing extra allowed: only {} fits.")
    new = transform_schema(OrchestratorPlan)
    task = new["$defs"]["PlannedTask"]["properties"]["constraints"]
    ref = task.get("$ref", "") or json.dumps(task)
    fields = list(new["$defs"]["PlanConstraints"]["properties"])
    print(f"\n  after: constraints -> {ref}")
    print(f"    with {len(fields)} named fields: {', '.join(fields[:5])}, ...")
    print("  tests/test_structured_output_schemas.py now checks every reply shape this way.")


def step_7_what_tokens_and_effort_showed() -> None:
    """Real results from your laptop (14 Oct), recorded in docs/PROJECT_PROGRESS.md."""
    heading(7, "What the token and effort labs found on real calls (recorded results)")
    print("  Tokenization lab: Claude's own count 1,889 tokens per request on average;")
    print("    tiktoken counted 41.5% fewer, a GPT-2 tokenizer 32.6% fewer. Estimating cost")
    print("    with either would have under-priced it by a third or more.")
    print("  Effort lab: 3 questions x 5 effort levels, $0.114 and $0.119 for two runs.")
    print("    It found a word-limit cut-off (text_to_sql max_tokens 800 -> 1500) and a")
    print("    scoring bug, not a model problem.")


def step_8_fine_tuning_in_one_table() -> None:
    """The QLoRA benchmark (ADR-007), from finetuning/results_template.md."""
    heading(8, "Fine-tuning: the QLoRA benchmark's headline numbers (recorded results)")
    rows = [
        ("base, zero-shot", "0.017", "6.8 s"),
        ("base, few-shot", "0.100", "3.8 s"),
        ("QLoRA fine-tuned", "1.000", "4.4 s"),
    ]
    print("  model              execution accuracy   mean latency")
    for name, acc, lat in rows:
        print(f"  {name:<18} {acc:>12}         {lat:>8}")
    print("\n  1.000 holds only inside one fixed family of question templates, so it's")
    print("  benchmarked, not deployed (ADR-007).")


def main() -> None:
    use_utf8_output()
    step_1_versioned_prompts()
    step_2_what_a_call_sends()
    step_3_what_it_costs()
    step_4_what_is_retried()
    step_5_the_repair_loop()
    step_6_the_empty_box_bug()
    step_7_what_tokens_and_effort_showed()
    step_8_fine_tuning_in_one_table()
    print("\nDone. Every step above used the copilot's real code, and no AI call was made.")


if __name__ == "__main__":
    main()
