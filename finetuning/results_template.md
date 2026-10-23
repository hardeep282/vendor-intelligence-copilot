# Day 9 fine-tuning benchmark — results

**Status: template, not a result.** No GPU was available in the cloud sandbox that scaffolded
this benchmark (23 Oct), so every number below is a placeholder. Fill this in after running
`day9_qlora_colab.ipynb` followed by `eval_compare.py` — see `finetuning/README.md`'s
"How to run it" section.

## Setup

- Base model: `Qwen/Qwen2.5-1.5B-Instruct`
- Fine-tuning method: QLoRA (4-bit NF4 + LoRA, r=16, alpha=32), completion-only loss
- Training data: `evals/datasets/sql_pairs_v1.jsonl` — 400 execution-verified pairs, 85/15
  train/held-out split (seed=42), so held-out n = `<fill in>`
- Date run: `<fill in>`
- Hardware: `<fill in — e.g. Colab free-tier T4>`

## Results

Paste the table `eval_compare.py` prints here verbatim.

| variant | n | executable_rate | execution_accuracy | mean_latency_s |
|---|---|---|---|---|
| base_zero_shot | | | | |
| base_few_shot | | | | |
| qlora | | | | |
| frontier_api (optional) | | | | |

## Reading the numbers

- **executable_rate**: fraction of generated SQL that ran against the real snapshot without a
  DuckDB error, regardless of whether the rows were correct. A low rate here means the model is
  producing invalid SQL (wrong columns, bad syntax), not a subtler correctness problem.
- **execution_accuracy**: fraction where the generated SQL's result rows matched the
  ground-truth SQL's result rows exactly (both re-executed against the same real snapshot,
  floats rounded to 2dp). This is the number that answers "did fine-tuning help."
- **mean_latency_s**: wall-clock seconds per generation, single example, no batching — a rough
  cost signal, not a production benchmark.

## What this does and doesn't tell you

- All three (four) variants get exactly one generation attempt per question — no retry loop, no
  validator-driven self-correction. That's deliberately different from the production
  `copilot.sql.service.TextToSqlService` path, which does retry against the validator; this
  benchmark isolates "how good is the model's first guess," not "how good is the whole system."
- The few-shot baseline uses simple lexical (Jaccard) retrieval over the training pairs, the same
  shape as the production `copilot.sql.examples.retrieve_examples` — not embeddings. A
  from-scratch embedding retrieval baseline was out of scope for a Day-9 sprint benchmark.
- 400 pairs total (340 train / 60 held-out, at an 85/15 split) is a small benchmark. Treat any
  single-digit percentage-point difference between variants as noise unless it holds up after
  re-running with a different split seed.

## Decision

See `docs/adr/007-finetuning-outcome.md` for the adopt/don't-adopt decision made from these
numbers, and the reasoning behind it.
