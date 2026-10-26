# Day 9 fine-tuning benchmark — results

**Status: real result**, run 25-26 Oct 2026 on Colab's free T4 tier. Three bugs found and
fixed in the *measurement* code before trusting any number (few-shot retrieval leakage,
unlearnable vendor casing in the training data, an SQL-extraction bug that glued trailing
model prose onto otherwise-correct SQL), then a fourth, real training bug (see below) that
needed the GPU step rerun, not just re-evaluated. Full story in `docs/BUILD_LOG.md`'s 25 Oct
entries.

## Setup

- Base model: `Qwen/Qwen2.5-1.5B-Instruct`
- Fine-tuning method: QLoRA (4-bit NF4 + LoRA, r=16, alpha=32, dropout=0.05), completion-only
  loss, 3 epochs, effective batch size 16 (4 × grad-accum 4), learning rate 2e-4
- Training data: `evals/datasets/sql_pairs_v2.jsonl` — 400 execution-verified pairs (v2: vendor
  names matched case-insensitively, not v1's unlearnable stored-casing literals), 85/15
  train/held-out split (seed=42) → 340 train / 60 held-out
- `MAX_LEN` 1024 (not the original 512 — see "the real bug" below)
- Date run: 25-26 Oct 2026
- Hardware: Google Colab, free-tier T4 GPU

**The real bug, worth recording here too:** the first training attempt completed all 66 steps
reporting a training loss of exactly `0.000000` throughout. Checked directly: every one of the
adapter's 196 LoRA B matrices (zero-initialized before training, by design) was still exactly
zero afterward, and the base model and "fine-tuned" model produced byte-identical output —
the adapter was a mathematical no-op. Cause: the real prompt (schema card + question +
case-insensitivity instruction) runs 650-700+ tokens on its own, already past the original
512-token cap before the SQL answer was even appended, so every training example lost its
entire answer to truncation. Fixed by raising `MAX_LEN` to 1024 and retraining for real; the
retrained adapter's three sanity-check examples (end of the training notebook) matched their
ground-truth SQL exactly, word for word, before this results table was trusted.

## Results

```
variant             n  executable_rate  execution_accuracy  mean_latency_s
--------------------------------------------------------------------------
base_zero_shot     60             0.25               0.017           6.764
base_few_shot      60            0.333                 0.1           3.828
qlora              60              1.0                 1.0           4.424
```

| variant | n | executable_rate | execution_accuracy | mean_latency_s |
|---|---|---|---|---|
| base_zero_shot | 60 | 0.25 | 0.017 | 6.764 |
| base_few_shot | 60 | 0.333 | 0.1 | 3.828 |
| qlora | 60 | 1.0 | 1.0 | 4.424 |
| frontier_api (optional) | — | not run | not run | — |

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
  re-running with a different split seed. A 0.983 gap (qlora vs base_zero_shot) is not that kind
  of noise.
- **The 1.0 needs one honest qualifier.** `sql_pairs_v2` is built from a small, fixed family of
  question templates ("What is X's Y?", "Which has the higher Y, A or B?", "How did X's monthly
  demand trend...") applied to real vendor names. A perfect score says the model has thoroughly
  learned *that template family* on real schema and real data — a genuine, non-trivial result
  for a 1.5B model — not that it would handle an arbitrary unseen question type equally
  perfectly. The held-out set is a random 15% split of the same template family, not a
  held-out *template*.

## Decision

See `docs/adr/007-finetuning-outcome.md` for the adopt/don't-adopt decision made from these
numbers, and the reasoning behind it.
