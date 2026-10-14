# Project Progress: Vendor Intelligence Copilot

Last updated: Wed 14 Oct 2026 (Day 5 of the 10-day sprint, sprint plan v3, in progress -- steps
1-5 of 6 shipped; step 6 (Model Selection Agent) ahead)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | Build done; repo pushed to GitHub (14 Oct) |
| 2 | Production skeleton live | Code done and tested. Waiting on you: AWS resources, domain, GitHub variables |
| 3 | LLM service, text-to-SQL, effort and tokenization labs | Build done: 8 of 9 steps shipped (step 7 skipped, see below) |
| 4 | RAG and advanced RAG | Build done: 7 of 7 steps shipped |
| 5 | ML tools for the agents | Build in progress: steps 1, 2, 3, 4, 5 of 6 shipped |
| 6 | Multi-agent system in LangGraph | Not started |
| 7 | Guardian, guardrails, approvals | Not started |
| 8 | Product, API keys, latency budget, evals in CI, release v0.1 | Not started |
| 9 | Fine-tuning benchmark and MCP (MCP never cut) | Not started |
| 10 | Package and launch the job campaign | Not started |

## Day 3 checklist (sprint doc v2/v3 D3)

| # | Item | Status |
|---|---|---|
| 1 | LLM client wrapper (retries, timeouts, caching, `@traceable`, TTFT/latency/tokens/cost) | **Done** |
| 2 | Prompts as versioned YAML; Pydantic outputs with forced tool call and repair retry | **Done** (`copilot.llm.prompts`, `prompts/vendor_insight/v1.yaml`; repair loop was already in the client) |
| 3 | Refactor `vendor_insights.py` into `InsightService` | **Done** (`copilot.insights.service.InsightService`; model id now lives only in the prompt YAML) |
| 4 | Text-to-SQL: schema linking, business rules, 3 retrieved golden examples | **Done** (`copilot.sql.service.TextToSqlService`, `copilot.sql.schema`, `copilot.sql.examples`) |
| 5 | Layered sqlglot validator + `policies/sql_rules.yaml` | **Done** (`copilot.sql.validator`; built ahead of step 4 since step 4's self-correction loop needs it; a 6th layer, data-coverage, was added while building step 4) |
| 6 | Golden v2 as a LangSmith dataset + evaluators | **Done** (`copilot.evals.evaluators`, `copilot.evals.langsmith_sync`; actual push needs your `LANGSMITH_API_KEY` -- run `scripts/push_golden_to_langsmith.py` on your machine) |
| 7 | Question->SQL pair generator | Not started (cut-first item; may move to Day 9 regardless) |
| 8 | Temperature lab | **Done, as an effort lab** -- see correction below (`copilot.evals.effort_lab`; real sweep needs your `ANTHROPIC_API_KEY` -- run `scripts/run_effort_lab.py` on your machine) |
| 9 | Tokenization lab | **Done** (`copilot.evals.tokenization_lab`; real sweep needs network access beyond just your API key -- run `scripts/run_tokenization_lab.py` on your machine) |

### Correction found during step 1 (ADR-005)

Anthropic's current model generation (the one this project uses -- Sonnet 5, Haiku 5.5, Opus
5.5) **does not accept `temperature`, `top_p` or `top_k` in the Messages API**: confirmed against
the installed SDK (`anthropic==1.13.0`, which has no such parameters on `messages.stream`/
`.create`) and against Anthropic's own Sonnet 5.5 migration guide ("a non-default value now
returns a 400 error... Remove them"). The nearest per-call lever this generation exposes is
`output_config.effort` (`low`/`medium`/`high`/`xhigh`/`max`), which is not a temperature
substitute (it trades reasoning depth for latency/cost, not output diversity at fixed sampling).

`copilot.llm.client.LLMClient` was built accordingly: `complete()`/`structured()` take an
optional `effort: Literal["low","medium","high","xhigh","max"] | None`, never `temperature`.
Step 8 of today's plan is now an **effort lab**: same question, same metrics (execution
accuracy, grounding, output diversity, latency, cost), `effort` swept across its five values
instead of 3 temperatures x 5 runs. Full writeup: `docs/adr/005-llm-provider.md`.

## Day 4 checklist (sprint doc v3 D4)

| # | Item | Status |
|---|---|---|
| 1 | Knowledge docs + 8-10 synthetic vendor contracts | **Done** -- found already built uncommitted at the start of this chat (`knowledge/`), verified against the live disclosure policy and committed (10 contracts, 4 methodology docs) |
| 2 | Heading-aware chunking with doc type/vendor/version/data-class/role metadata | **Done** (`copilot.rag.chunking`; 14 docs -> 119 chunks) |
| 3 | Local sentence-transformers embeddings; Chroma collection with idempotent upserts | **Done** (`copilot.rag.embeddings`, `copilot.rag.store`; real model run needs your machine -- `scripts/build_rag_index.py`) |
| 4 | Hybrid retrieval: BM25 + vectors fused with RRF; cross-encoder reranker | **Done** (`copilot.rag.retrieval`; reranker cut, see below) |
| 5 | Permission filter inside the vector query | **Done** (`copilot.rag.permissions.PermissionedRetriever`) |
| 6 | Corrective RAG loop in LangGraph | **Done** (`copilot.rag.corrective.CorrectiveRagService`) |
| 7 | 20 labelled questions: recall@5, MRR, Ragas | **Done, Ragas cut to faithfulness + context_recall** (see below) |

**Cut-first item for step 7:** the full Ragas suite (faithfulness, answer relevancy, context
precision, context recall) reduced to faithfulness + context_recall only, per this step's own
cut-first note (`docs/HANDOFF.md`). Built as two small structured-output LLM-judge calls
(`copilot.evals.rag_quality`) reusing `copilot.evals.evaluators.EvalScore`, rather than pulling
in the `ragas` package -- consistent with this repo's existing hand-written evaluator pattern,
not a new ADR-level decision.

**Cut-first item for step 4:** a cross-encoder reranker on top of the fused BM25+vector
candidates. The step's job was to prove the fusion mechanics (BM25 index, RRF math, candidate
pool sizing) are correct; a reranker is a real quality lever but a second model to load and run
per query, and `RetrievedChunk` already carries the full chunk text so one can be bolted on
later as a third stage without changing `copilot.rag.retrieval`'s contract.

## Day 5 checklist (sprint doc v3 D5, plus Addendum A1's Model Selection Agent)

| # | Item | Status |
|---|---|---|
| 1 | Forecast tool: ETS vs naive, WAPE/MASE/bias on a rolling backtest | **Done, real numbers run in this sitting** (`copilot.ml.forecast`, `copilot.ml.metrics`) -- see below |
| 2 | SKU risk classifier: sklearn Pipeline (Random Forest), leakage-safe features, calibration, SHAP | **Done, synthetic fixture run in this sitting** (`copilot.ml.risk_classifier`) -- see below |
| 3 | XGBoost comparison on the same split | **Done** (`copilot.ml.risk_classifier.compare_models()`) -- see below |
| 4 | Inventory tools: safety stock, reorder point, EOQ | **Done, real numbers run in this sitting** (`copilot.ml.inventory`) -- see below |
| 5 | Pydantic schemas + unit tests for every tool; run-log (MLflow cut, CSV instead per sprint doc) | **Done** -- schemas + tests for all 3 tools; CSV run-log (`copilot.ml.run_log`) |
| 6 | Model Selection Agent (Addendum A1): LangGraph propose -> critique -> revise, LLM-judge eval | Not started |

**Why steps 1 & 4 and not 2-3 first:** `portfolio_monthly_demand`/`vendor_monthly_demand` are
already licence-safe aggregates in this repo's own snapshot, so the forecast and inventory
tools compute real final numbers in this session -- no API key, no network, no SKU-level data.
The risk classifier needs per-SKU features (margin, turnover, etc.), which the licence guard
correctly keeps out of this repo's snapshot (`check_table` rejects SKU-level columns) and which
R1 in `docs/RAID.md` already flags as an open licence question even in the public analytics
repo. Steps 2-3 will follow the same pattern as every earlier "needs real data" item in this
project (effort lab, tokenization lab, RAG index): pipeline code and tests built and run for
real against clearly-synthetic SKU fixtures now, with a script for a real run against the
licensed `vw_PortfolioHealth` sheet on your machine for real accuracy/F1 numbers.

**Steps 2-3-5, done:** `copilot.ml.risk_classifier` builds a leakage-safe Random Forest +
XGBoost comparison (`compare_models()`, 4 combinations: RF/XGBoost x leaky/leakage-safe on one
split), tested against `make_synthetic_skus()` -- a fixture built from one shared latent "SKU
health" factor so the leakage story is real, not just labelled. Two rounds of debugging were
needed before the leaky-vs-safe differential actually showed up (see `docs/BUILD_LOG.md`'s
2026-10-14 entry); the second round found that `SalesToPurchaseRatio` algebraically reconstructs
`ProfitMargin` (`= StockTurnover * (1 + MarkupPct)`) even though it isn't itself a raw margin
column, and had to be added to `LEAKING_FEATURES`. `copilot.ml.run_log` is the CSV run-log (step
5, MLflow cut-first per the sprint doc) all three ML tools now log to.
`scripts/train_risk_classifier.py` is the real-data counterpart, same never-in-chat convention
as the other real-data scripts.

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 33 | 285 | `uv run pytest -q`; +12 `copilot.llm`, +12 prompts + `InsightService`, +29 SQL validator, +16 schema/examples/text-to-SQL service, +22 evaluators/langsmith_sync, +10 golden v2, +4 effort lab, +5 tokenization lab, +3 evaluator column-name fix, +10 rag corpus, +9 chunking, +7 embeddings, +10 store, +12 retrieval (BM25 + RRF), +2 store `where` filter, +10 permission filter, +6 corrective RAG, +19 eval harness (golden/metrics/quality), +12 ml metrics, +10 forecast tool, +12 inventory tools, +12 risk classifier, +6 run-log |
| Golden questions | 40 (27 dev, 10 test, 3 adversarial) | 46 (27 dev, 16 test, 3 adversarial) | golden v2 adds the 6 text-to-SQL trap questions from the spec; v1 stays frozen at 40 for history |
| Execution accuracy, grounding, leakage rate | n/a | evaluators built + tested; no end-to-end run yet | `copilot.evals.evaluators.execution_accuracy`/`leakage_free`, 17 tests pass; running them against real `TextToSqlService` output needs your API key, same as the effort/tokenization labs |
| SQL validator: structural + semantic + coverage rules | n/a | 29/29 tests pass, 0 false positives on 33 real golden queries | every trap in `docs/specs/text_to_sql_safety.md`'s trap table has a BLOCK test and an ALLOW test |
| Text-to-SQL self-correction loop | n/a | 4/4 tests pass (first-try, 1-retry, abstain, exhausted) | validator rejection fed back as the next turn; abstains after 2 retries rather than run bad SQL |
| LLM client: retries, repair loop, caching, no-temperature guard | n/a | Tested | against a fake SDK, no API key used (`tests/test_llm_client.py`) |
| First real LLM call (`InsightService`, DIAGEO, viewer role) | n/a | $0.01127, 7.31s, 1 attempt, 0 repairs | run on your machine, 14 Oct; caught and fixed a `max_tokens` truncation bug (see BUILD_LOG) |
| Tokenization lab: provider vs. tiktoken vs. HF, cost/1000 req | n/a | provider 1889.2 tok avg; tiktoken -41.5% (1092.2); HF gpt2 -32.6% (1252.8); $/1000req: $5.28 / $3.68 / $4.01 | run on your machine, 14 Oct; both local tokenizers would make you underestimate the real cost by a third to over 40% |
| Effort lab real sweep (3 questions x 5 effort levels) | n/a | 2 runs: $0.11408 then $0.11907, exec_acc = 0.67 both times (gq-045 scoring 0 every time, root cause below) | run on your machine, 14 Oct; found and fixed a `max_tokens` truncation case (`text_to_sql` prompt, `800 -> 1500`) **and** a real scoring bug (below) -- `exec_acc` wasn't actually a model problem |
| `execution_accuracy` scoring bug: required exact column-name match | n/a | fixed + 3 tests | `_row_matches()` compared rows by column-name set, so a correctly-computed answer with a different column alias (e.g. `blended_margin` vs. the golden's `blended_margin_pct`) scored 0 even though the number was right; now compares by value in column order, per the spec ("values, not just row count") |
| Knowledge corpus (Day 4 step 1) | n/a | 14 docs: 4 methodology-family (public/internal) + 10 synthetic contracts (confidential) | recovered from an uncommitted working-tree state, verified against the live disclosure policy before committing |
| Chunking (Day 4 step 2) | n/a | 14 docs -> 119 chunks (16-1100 chars, avg 260) | heading-aware, by data_class: confidential 80 / public 31 / internal 8 |
| Embeddings + Chroma store (Day 4 step 3) | n/a | idempotency verified end to end (119 embedded first run, 0 embedded / 119 unchanged second run against unchanged chunks, via FakeEmbedder + a temp Chroma dir) | real `all-MiniLM-L6-v2` run still needs your machine -- `scripts/build_rag_index.py` |
| Hybrid retrieval (Day 4 step 4) | n/a | 12/12 tests pass: BM25 ranking, RRF formula verified against hand-computed values, a chunk with zero lexical overlap surfaced purely via the vector ranking | reranker cut (see checklist note above); real end-to-end quality numbers wait for step 7's eval set |
| Permission filter (Day 4 step 5) | n/a | 12/12 tests pass (10 permissions + 2 store `where`): every role sees exactly its policy-allowed classes, the vector filter is proven to run inside the ANN query (not after) via a small-candidate-pool test that would under-fill under a post-hoc filter, BM25's role-scoped index excludes an ineligible chunk entirely rather than just ranking it low | authority is the live `DisclosurePolicy`, re-derived per call -- never the chunk's own `allowed_roles` field |
| Corrective RAG loop (Day 4 step 6) | n/a | 6/6 tests pass: happy path (grade relevant -> generate), one rewrite then success, exhausts the retry budget and abstains, abstains without wasting an LLM call grading an empty retrieval, never cites a chunk id it wasn't shown, ignores a grade for a chunk id outside the retrieved set | reranker-style web-search fallback cut (no web search by design, ADR-002) -- rewrites and retries the same corpus instead |
| RAG eval harness (Day 4 step 7) | n/a | 19/19 tests pass; 20/20 golden questions verified to resolve to exactly one real chunk against the live corpus; recall@5/MRR run for real end to end with `FakeEmbedder` (mean recall@5 0.40, MRR 0.258 -- expected to be noise-level since `FakeEmbedder` isn't semantic, see below) | real embedding-model numbers and the `--quality` (faithfulness/context_recall) run both need `scripts/run_rag_eval.py` on your machine |
| Forecast tool (Day 5 step 1), portfolio, real run | n/a | 22/22 tests pass; real backtest: ETS WAPE 0.1153, MASE 1.516, bias -63,673; naive WAPE 0.1153, MASE 1.516, bias -63,671 (essentially tied -- AutoETS's trend reduces to ~none on this series); naive chosen by WAPE tiebreak | matches the analytics repo's own `forecast_backtest.py` "portfolio naive 11.8%" baseline as a sanity check; full reasoning in `docs/BUILD_LOG.md` |
| Inventory tools (Day 5 step 4), real run from the forecast above | n/a | 12/12 tests pass; real plan (3-month horizon, 1-period lead time, 95% service level, $500/order, $0.50/unit/yr holding): mean demand/period 3,758,005, std dev 363,277, safety stock 597,537, reorder point 4,355,542, EOQ 300,320 | caught and fixed a bug before shipping: std dev must come from historical variability, not variance across a (possibly flat) forecast -- see `docs/BUILD_LOG.md` |
| SKU risk classifier (Day 5 steps 2-3), synthetic fixture run | n/a | 12/12 tests pass; n=2000: RF accuracy 0.834 -> 0.820, F1 0.291 -> 0.211; XGBoost accuracy 0.898 -> 0.886, F1 0.667 -> 0.596 (leaky -> leakage-safe) | leakage inflates both models' scores in the expected direction; `SalesToPurchaseRatio` had to be added to `LEAKING_FEATURES` after it was found reconstructing `ProfitMargin` algebraically -- see `docs/BUILD_LOG.md`. Synthetic data, so direction is the finding, not the exact figures |
| CSV run-log (Day 5 step 5) | n/a | 6/6 tests pass; smoke-tested end to end via `scripts/train_risk_classifier.py` against a synthetic CSV | MLflow cut-first per sprint doc; `run_log.csv` covered by the existing blanket `*.csv` gitignore rule |

## Decisions

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot ·
ADR-003 EC2 + Compose runtime · ADR-004 secrets in SSM, OIDC for CI · ADR-005: direct Anthropic
API, not Bedrock, for now -- and the temperature/effort correction above. No new ADR for Day 4 --
the embedding model (local sentence-transformers), vector store (Chroma), the RRF fusion
constant (k=60, Cormack et al. 2009), the Corrective RAG loop's no-web-search simplification
(follows from ADR-002, not a new decision), and building the Ragas-reduced quality evaluators
by hand instead of the `ragas` package (follows the pattern `copilot.evals.evaluators` already
set in Day 3) all just follow already-made or already-standard choices rather than being a new
build-vs-buy decision with real alternatives measured against it.

## Costs to date

AWS $0, domain $0, LLM ~$0.01 (one real call, 14 Oct, on your machine with your dev key --
`InsightService` on DIAGEO, after fixing a `max_tokens` bug that had been doubling the cost via
unnecessary repair-loop retries). Expected once Day 2 resources exist: about $22 per month on
AWS (Mumbai).

## Live URLs

None yet. Target: `https://api.vendor.<domain>/health`.

## Next step

Me: Day 5 steps 1, 2, 3, 4 & 5 are all built and run for real (or against synthetic data where
licence rules require it) -- continuing now with step 6, the Model Selection Agent (Addendum
A1): a LangGraph propose -> critique -> revise flow, following the `CorrectiveRagService`
pattern from Day 4, evaluated with an LLM judge. You: run `scripts/train_risk_classifier.py`
against your real `vw_PortfolioHealth` export whenever convenient, for the real accuracy/F1
numbers to replace the synthetic ones in this doc. Carried forward, still open and not urgent:
`scripts/build_rag_index.py` + `scripts/run_rag_eval.py` (Day 4, real embedding index and
recall@5/MRR), a third re-run of `scripts/run_effort_lab.py`, a real `TextToSqlService` call,
Docker Desktop install/engine status, AWS resources, domain, GitHub variables from Day 2.
