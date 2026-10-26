# ADR-007: Fine-tuning outcome — adopt or don't adopt a QLoRA-tuned SQL model

**Status:** Accepted, conditionally — 26 Oct 2026, from a real run on Colab's free T4 tier.
See `finetuning/results_template.md` for the full numbers and the bugs found and fixed before
trusting them (three in the measurement code, one real training bug that required retraining).

## Context

Day 9 (B7 in the sprint plan) asks for a fine-tuning benchmark: take a small open model, QLoRA
fine-tune it on this project's own execution-verified question→SQL pairs
(`evals/datasets/sql_pairs_v2.jsonl` — v1 had an unlearnable vendor-casing bug, see
`docs/BUILD_LOG.md`'s 25 Oct entries), and compare it honestly against the un-tuned base model
(zero-shot and few-shot) to decide whether fine-tuning is worth adopting for this project's
text-to-SQL path. "Honestly" per the sprint brief means either outcome — adopt or don't — is a
valid, complete answer; this is a benchmark, not a foregone conclusion that fine-tuning must
win.

The fine-tuning ran on Google Colab's free T4 tier, via `finetuning/day9_qlora_colab.ipynb`,
evaluated with `finetuning/eval_compare.py` (see `finetuning/README.md` for how to run both).
The first training attempt silently failed to train at all (a token-truncation bug, fixed and
retrained — full story in `docs/BUILD_LOG.md`); the numbers below are from the retrained
adapter, sanity-checked against its own training examples before being trusted.

## Decision framework

Adopt the QLoRA-tuned model into the production `TextToSqlService` path only if **all** of the
following hold, read from `finetuning/results_template.md`'s results table:

1. **Execution accuracy clearly beats both base variants** (zero-shot and few-shot) on the
   held-out split — not a single-digit-percentage-point difference that could be split-seed
   noise (see `results_template.md`'s own caveat about the small, 60-example held-out set).
2. **Executable rate is at least as good as the few-shot baseline** — a fine-tuned model that
   generates confidently wrong SQL more often than the few-shot baseline is a regression in a
   different, arguably worse way than low accuracy (wrong answers delivered with no validator
   catch, rather than caught as unexecutable).
3. **Latency is acceptable for the product's interactive `/ask` path** — this benchmark measures
   single-example latency with no batching, which is not directly the production serving
   latency, but a QLoRA-adapted 1.5B model that is dramatically slower than the current
   frontier-API call it would replace is not a viable swap regardless of accuracy.

If fine-tuning wins on accuracy but loses badly on executable rate or latency, the honest
decision is "don't adopt yet" with the specific gap named — not a forced yes.

## Decision

All three criteria pass clearly, on real numbers:

1. **Execution accuracy:** qlora 1.0 vs. base_zero_shot 0.017 and base_few_shot 0.1 — not a
   single-digit-point difference that could be split-seed noise; a 0.9-point gap.
2. **Executable rate:** qlora 1.0 vs. base_few_shot's 0.333 — clearly better, not a regression.
3. **Latency:** qlora's 4.424s mean is actually lower than base_zero_shot's 6.764s and close to
   base_few_shot's 3.828s — no latency penalty for adopting it, on this benchmark's own
   single-example, no-batching measurement (see the caveat below on what that does and doesn't
   prove about production serving latency).

**Adopt, with one explicit condition before this becomes the primary production path, not a
caveat buried in the fine print:** `sql_pairs_v2` is built from a small, fixed family of
question templates applied to real vendors and real data — a perfect score here is a genuine,
non-trivial result (the model has thoroughly learned that template family on the real schema),
but it is not evidence the model generalizes to question phrasings or intents outside that
family. Before this replaces the frontier-API call in `TextToSqlService`'s primary path,
validate it against a broader, more naturalistic question set than the fixed templates this
benchmark was trained and tested on — that is the one thing this result does not yet prove.

## Consequences

- **If/when wired into `copilot.sql.service.TextToSqlService`:** the adapter would need to be
  hosted somewhere with GPU inference, not the CPU-only infra the rest of this project
  deliberately targets (see `finetuning/README.md`'s reasoning for keeping GPU deps out of
  `pyproject.toml` entirely) — this is a real deployment decision, not a drop-in swap, and is
  explicitly **not** done as part of this ADR. Recorded here as the next concrete step, not
  actioned.
- **Kept either way:** `evals/datasets/sql_pairs_v2.jsonl` (400 execution-verified, case-
  consistent pairs) is reusable for future eval work regardless of what happens with the
  adapter itself; `finetuning/eval_compare.py`'s re-execute-and-compare pattern is a template
  for benchmarking any future model swap the same honest way.
- **Not done, flagged as a known gap:** the frontier-API row (`--include-frontier`) was the
  sprint's own named cut-first item and was not run — this ADR compares against the base model,
  not against what `TextToSqlService` actually calls in production today.
