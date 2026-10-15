# Trade-off Log

Addendum A1 §2.2: every change that could affect quality, cost or latency (model swap, prompt
change, new guardrail, caching, chunking change, retrieval change, temperature change) is
re-run against the golden set (`evals/datasets/golden_v1.jsonl`) before and after, and logged
here. Never log an invented number -- write "not measured" and add the measurement to the next
day's plan instead.

This file did not exist through Days 1-6; backfilled on Day 7 (15 Oct) once the gap was
noticed during the handoff cross-check. Entries below are reconstructed from `docs/BUILD_LOG.md`
where a real before/after exists; nothing here is a new invented figure.

| Date | Change | Reason | Accuracy / faithfulness before -> after | Cost per query before -> after | p50 / p95 latency before -> after | Kept? | ADR |
|---|---|---|---|---|---|---|---|
| 14 Oct | `execution_accuracy` scoring fixed to compare row values in column order, not column-name sets | A correct answer with a different column alias (`blended_margin` vs. golden's `blended_margin_pct`) scored 0 even though the number was right | effort-lab exec_acc 0.67 before and after this run (gq-025/gq-045-class cases not yet re-scored on the full set) | not measured | not measured | Yes | n/a (bug fix, not a design trade-off) |
| 15 Oct | SQL validator: new `_check_cost_limit` (`sql_cost_limit`) blocks an unconditioned/cross join unless `WHERE` references columns from >=2 joined tables by table-qualified name | 23-case privacy suite surfaced an unguarded gap: `LIMIT 200` bounds output rows, not join computation cost | Verified `gq-025` (genuine bounded-by-`WHERE` self-join) still passes -- not a full golden-set rerun; full execution-accuracy before/after not measured | not measured (no LLM call in this check -- pure sqlglot AST inspection) | not measured | Yes | ADR-006 (pending, Guardian/validator design) |
| 15 Oct | Guardian's `unverified_grounding` finding routes an unresolved Verifier draft to ESCALATE rather than BLOCK | An unconfirmed-safe draft (redraft budget exhausted, `verified=False`) is not the same as a known-unsafe one; BLOCK would silently drop a possibly-correct answer with no path to recovery | Not measured against the golden set (no golden question currently exercises the redraft-exhaustion path) -- proposed default pending ADR-006 answer | n/a | n/a | Pending ADR-006 | ADR-006 (pending) |

## Open measurement debt (carried from PROJECT_PROGRESS.md "Next step")

The following Day 7 changes are deterministic (no LLM call) so cost/latency columns above are
genuinely "not measured" rather than omitted by oversight: `sql_cost_limit`, the Guardian's 8
checks, the input gate, PII/canary/audit-log, trace masking. A full golden-set execution-accuracy
rerun after the `sql_cost_limit` and `execution_accuracy`-scoring fixes is still owed and should
be added here, not just asserted as "no regression on gq-025", once `scripts/run_effort_lab.py`
or an equivalent full-set run happens again.
