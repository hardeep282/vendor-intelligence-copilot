# ADR-007: Fine-tuning outcome — adopt or don't adopt a QLoRA-tuned SQL model

**Status:** PENDING — scaffolded 23 Oct 2026, not yet decided. No GPU was available in the
cloud sandbox that built this scaffolding, so this ADR records the decision framework now and
waits for a real run's numbers before anything under "Decision" is filled in.

## Context

Day 9 (B7 in the sprint plan) asks for a fine-tuning benchmark: take a small open model, QLoRA
fine-tune it on this project's own execution-verified question→SQL pairs
(`evals/datasets/sql_pairs_v1.jsonl`, 400 pairs generated and verified for real on 23 Oct — see
`docs/BUILD_LOG.md`), and compare it honestly against the un-tuned base model (zero-shot and
few-shot) to decide whether fine-tuning is worth adopting for this project's text-to-SQL path.
"Honestly" per the sprint brief means either outcome — adopt or don't — is a valid, complete
answer; this is a benchmark, not a foregone conclusion that fine-tuning must win.

The fine-tuning itself needs a GPU this sandbox doesn't have. `finetuning/day9_qlora_colab.ipynb`
and `finetuning/eval_compare.py` were built and are ready to run in Google Colab (free T4 tier);
see `finetuning/README.md` for the full "how to run it" instructions. This ADR will be filled in
once that run produces real numbers, written to `finetuning/results_template.md`.

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

`<fill in once finetuning/results_template.md has real numbers>`

## Consequences

`<fill in — if adopted: what changes in copilot.sql.service.TextToSqlService and where the
adapter/model gets deployed; if not adopted: what, if anything, from this benchmark is worth
keeping (e.g. the 400-pair golden-adjacent dataset is reusable for future eval work regardless
of this decision)>`

## Status note

This ADR stays PENDING until someone runs the Colab notebook and `eval_compare.py` end to end
and fills in the three sections above with real numbers and a real decision. Do not mark this
Accepted based on the scaffolding alone — the scaffolding is untested against a real training
run.
