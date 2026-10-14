# Project Progress: Vendor Intelligence Copilot

Last updated: Thu 15 Oct 2026 (Day 7 of the 10-day sprint, sprint plan v3 -- all 8 steps
shipped, Day 7 complete; injection classifier cut-first per the sprint doc)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | Build done; repo pushed to GitHub (14 Oct) |
| 2 | Production skeleton live | Code done and tested. Waiting on you: AWS resources, domain, GitHub variables |
| 3 | LLM service, text-to-SQL, effort and tokenization labs | Build done: 8 of 9 steps shipped (step 7 skipped, see below) |
| 4 | RAG and advanced RAG | Build done: 7 of 7 steps shipped |
| 5 | ML tools for the agents | **Build done: 6 of 6 steps shipped** |
| 6 | Multi-agent system in LangGraph | **Build done: 7 of 7 steps shipped** |
| 7 | Guardian, guardrails, approvals | **Build done: 8 of 8 steps shipped** (injection classifier cut-first) |
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
| 6 | Model Selection Agent (Addendum A1): LangGraph propose -> critique -> revise, LLM-judge eval | **Done** (`copilot.agents.model_selection.ModelSelectionAgent`) -- see below |

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

**Step 6, done:** `copilot.agents.model_selection.ModelSelectionAgent` -- the LangGraph
propose -> critique -> revise -> abstain loop Addendum A1 calls for, directly reusing the shape
Day 4's `CorrectiveRagService` already established (propose a model choice from a fixed,
closed catalog, scrutinize it with a second structured call, revise with the critique's
feedback folded in up to a retry budget, or abstain). No new ADR -- the shape, the retry-then-
abstain posture, and the eval-split philosophy below all follow from decisions already made
(handoff's placeholder ADR-006 wasn't needed). Eval harness
(`copilot.evals.model_selection_golden`/`metrics`/`quality`) splits free catalog-membership
checks from the one LLM-judged "is the reasoning actually grounded" check, same split the RAG
harness uses for recall@k/MRR vs. faithfulness/context_recall. Not run for real this sitting --
unlike the forecast/inventory/classifier tools, this agent needs a real `ANTHROPIC_API_KEY` for
every run (no free half), and no key is loaded in this session; `scripts/run_model_selection_eval.py`
is ready to run with your own key.

## Day 6 checklist (sprint doc v3 D6)

| # | Item | Status |
|---|---|---|
| 1 | `TaskSpec`/`AgentResult` Pydantic contracts | **Done** (`copilot.agents.contracts`) |
| 2 | Specialists: Data Analyst, Forecasting & Risk, Inventory Planning, Knowledge, Action | **Done** (`copilot.agents.specialists`) |
| 3 | Orchestrator: typed plan, `Send` fan-out, join, merge and conflict handling | **Done** (`copilot.agents.orchestrator.Orchestrator`) -- conflict handling logged only, not resolved (cut-first) |
| 4 | Verifier: numeric grounding, citations, contradictions; max 2 loops back | **Done** (`orchestrator.py`'s `_verify`/`_route_after_verify`/`_revise_draft`, `prompts/orchestrator_verify/v1.yaml`) |
| 5 | Per-agent budgets (steps/tokens/cost/latency) and temperature, timeouts; partial answers | **Done** (`AgentBudget.exceeds()` now actually enforced in `_run_specialist`; `effort` substitutes for `temperature` -- this model generation has no `temperature` param, see `copilot.llm.client`) |
| 6 | SQLite checkpointer locally; per-agent LangSmith run names/tags; LangGraph Studio | **Done except Studio** (`Orchestrator(checkpoint_path=...)`, `_ls_extra()`); LangGraph Studio cut-first (external tool, not code) |
| 7 | Run 10 multi-hop golden questions end to end | **Harness done, real run pending your key** (`copilot.agents.wiring`, `copilot.evals.orchestrator_golden`, `scripts/run_orchestrator_golden.py`) |

**Steps 1-3, done:** `copilot.agents.contracts.TaskSpec`/`AgentResult` are the typed envelope
every specialist and the Orchestrator pass between each other (master prompt C3: "never pass
free text to each other"). The five specialists (`copilot.agents.specialists`) are thin
`TaskSpec -> AgentResult` wrappers around already-tested Days 3-5 services/tools -- no new
business logic, just the C3 contract plus two new lookups needed to fill `data_classes`
honestly: `_sql_data_classes()` (parses generated SQL with sqlglot, looks up each table via the
live `DisclosurePolicy`) and `PermissionedRetriever.chunk_by_id()` (same idea for a cited
chunk). The Orchestrator (`copilot.agents.orchestrator.Orchestrator`) is this project's first
*parallel* LangGraph graph -- every prior graph (`CorrectiveRagService`, `ModelSelectionAgent`)
was sequential/conditional only. `_fan_out` returns one `Send` per planned task so independent
specialists run as separate parallel invocations, with `results: Annotated[list[AgentResult],
operator.add]` as the join; a real architectural bug surfaced and got fixed before shipping --
an empty plan left `run_specialist` (and therefore `draft`) unreached, fixed by routing an empty
plan straight to `draft` via its own `Send`. Conflict handling is logged only (`conflicts_noted`),
never resolved or re-queried, per the sprint doc's own cut-first list for this day.

**Step 4, done:** the Verifier reuses `ModelSelectionAgent`'s propose/critique/revise/accept
shape exactly -- `_verify` is the critique (one more structured LLM call, scoring `grounded`/
`citations_ok`/`sufficient`/`contradictions`), `_route_after_verify` is a pure routing function
(no LLM call), `_revise_draft` is pure bookkeeping that folds the verdict's feedback back into
the next `_draft` call via a new `feedback_block` in `orchestrator_draft`'s prompt. A draft that
still fails after `MAX_VERIFICATION_LOOPS` (2) redrafts is finalized anyway with `verified=False`
rather than looping forever -- a worse answer delivered honestly-flagged beats no answer.

**Step 5, done:** `AgentBudget.exceeds()` existed since step 1 but nothing called it until now.
`_run_specialist` waits on each specialist through a bounded `ThreadPoolExecutor`
(`max_latency_s`) -- a specialist that doesn't return in time becomes `status="failed"` with a
"timed out" gap rather than an unbounded hang (an honest limit: the Orchestrator can't force
arbitrary synchronous code to actually stop, only stop waiting on it). An `ok` result that
overran its cost/latency/llm_calls budget is downgraded to `status="partial"` with the specific
overage named in `gaps`. `AgentBudget.effort` substitutes for the sprint doc's original
"temperature" ask -- `copilot.llm.client`'s module docstring already established this Anthropic
SDK/model generation has no `temperature` parameter at all.

**Step 6, done (minus Studio):** `Orchestrator(checkpoint_path=...)` compiles the graph with a
local `langgraph.checkpoint.sqlite.SqliteSaver`; `answer(..., thread_id=...)` is the checkpoint
key a run can be inspected by afterwards (`select * from checkpoints where thread_id = ...`) --
the inspection LangGraph Studio would otherwise give, which is this step's one cut-first item
(an external tool to point at this process, not code to build). `_ls_extra()` tags each of
`plan`/`draft`/`verify`'s own LLM call with an orchestrator-node-specific LangSmith run name and
tags via `traceable`'s own `langsmith_extra` override -- no change needed to `LLMClient` itself
-- plus `run_action` tags its own call the same way. The other four specialists delegate to
Day 3-5 services whose internal LLM calls aren't yet agent-tagged; threading tags through those
pre-existing services was out of this step's scope and is noted rather than silently left undone.

**Step 7, done (harness):** `copilot.agents.wiring.build_executors()` is the one piece of glue
nothing else needed -- it turns the five `run_*` functions into the `dict[AgentName,
SpecialistExecutor]` map `Orchestrator` takes, against real services built the same way
`scripts/run_effort_lab.py`/`run_rag_eval.py` already build them. 10 multi-hop golden questions
(`evals/datasets/orchestrator_golden_v1.jsonl`, schema in `copilot.evals.orchestrator_golden`)
each need 2+ specialists chained together -- distinct from `golden.py`'s own "multi_hop"
category, which is multi-step *SQL* answered by one specialist alone. Each question is graded
structurally (did the plan cover every specialist it needed), not against a fixed reference
answer -- see the module's own docstring for why that's this step's stretch goal, not its floor.
`scripts/run_orchestrator_golden.py` is ready to run all 10 end to end on your machine with your
own `ANTHROPIC_API_KEY`; not run for real this sitting (same posture as every other real-key
script in this project).

## Day 7 checklist (sprint doc v3 D7)

| # | Item | Status |
|---|---|---|
| 1 | Guardian node: role policy, audience policy, provenance from data classes, raw-row check | **Done** (`copilot.guardrails.guardian.Guardian`) |
| 2 | Presidio PII + secret patterns; canary tokens in every agent's system prompt | **Done** (`copilot.guardrails.pii`/`canary`) |
| 3 | ALLOW/REDACT/BLOCK/ESCALATE with reason codes + audit log | **Done** (`Guardian.review()`, `copilot.guardrails.audit_log`) |
| 4 | Topology test: no path to END skips the Guardian | **Done** (`tests/test_orchestrator.py::test_every_path_to_end_passes_through_guardian`, asserted against the compiled graph's own edges) |
| 5 | Action draft behind an interrupt -> Guardian -> approver approves/edits/rejects | **Done** (`Orchestrator._approval_gate`/`resume_approval()`; skips gracefully with no checkpointer) |
| 6 | Input gate: injection heuristics, scope, length, rate limit, daily spend cap, kill switch | **Done except the classifier** (`copilot.guardrails.input_gate.InputGate`); **classifier cut-first** per the sprint doc |
| 7 | LangSmith trace masking (anonymizer rules, hidden restricted payloads) | **Done** (`copilot.guardrails.trace_masking.mask_run_payload`, wired as `process_inputs`/`process_outputs` on `LLMClient.complete`/`.structured`) |
| 8 | 23-case privacy-leakage suite in CI (15 + 8 SQL red-team) | **Done** (`tests/test_privacy_leakage_suite.py`, runs under plain `uv run pytest`) |

**Steps 1-3, done:** `Guardian.review()` runs 8 checks cheapest-first against anything shaped
like an `OrchestratorResult` (a `_Reviewable` Protocol, not an import of that class -- avoids a
circular import with `orchestrator.py`): canary leak, restricted-table-name leak, raw-row-shape
(10+ delimited lines), role policy (per `AgentResult.data_classes`), vendor-facing-audience
(an Action draft + any other specialist's non-public data in the same answer), secrets
(`SECRET_PATTERNS`, now in its own leaf module, `copilot.guardrails.secret_patterns`, so step 7's
trace masking can reuse them without an import cycle), PII (`copilot.guardrails.pii.find_pii`:
Presidio when its spaCy model is available, a regex fallback otherwise, cached so the test suite
doesn't reload the model per call), and grounding (`not verified` -> ESCALATE, not BLOCK --
unconfirmed-safe isn't known-unsafe). Worst-severity finding wins (`block` > `escalate` >
`redact` > `allow`); every finding's code lands in `reason_codes` regardless. `safe_answer` is
the real text on ALLOW, PII-redacted on REDACT, or one of two fixed generic messages on
BLOCK/ESCALATE. `copilot.guardrails.audit_log.log_decision`/`log_approval` append one JSON line
per Guardian verdict / approver decision to a local, gitignored `data/audit/guardian_log.jsonl`
-- independent of LangSmith on purpose (traces can be sampled/redacted/rotated; this file is the
compliance-grade record). Canary tokens (`copilot.guardrails.canary`, `CANARY-<AGENT>`) are
appended to every system prompt this project builds (`data_analyst`, `action`,
`knowledge_grade`/`_rewrite`/`_generate`, `orchestrator_plan`/`_draft`/`_verify`) -- one token
per call site, since a leak at the draft step versus the verify step says something different
about where it came from.

**Step 4, done:** `finalize` no longer edges straight to `END` -- it edges to `guardian`, the
only node with a path to `END` (after step 5, shared with `approval_gate`, itself only reachable
from `guardian`). The topology test asserts this against the *compiled* graph's own
`get_graph()` edges, not `_build_graph`'s Python source, which could silently drift from what's
actually compiled.

**Step 5, done:** an Action draft the Guardian allowed/redacted (never one it already
BLOCKed/ESCALATEd) routes to `_approval_gate`, which calls LangGraph's `interrupt()` and pauses
until `resume_approval(thread_id, decision, approver_role=, edited_answer=)` sends back
`Command(resume=...)`. Confirmed with a throwaway smoke script before wiring this in:
`interrupt()`/`Command(resume=...)` need a real checkpointer to mean anything (resuming without
one raises `RuntimeError` from LangGraph itself) -- an `Orchestrator` built with no
`checkpoint_path` skips the gate entirely rather than pausing on a run nothing can ever resume.
`resume_approval()` checks `approver_role in {"approver", "admin"}` in Python *before* touching
the graph at all. An `"edit"` decision is re-run through `self._guardian.review()` before its
text is accepted -- an approver's edit is new, unreviewed text that could reintroduce exactly
what the original draft didn't have.

**Step 6, done except the classifier (cut-first):** `InputGate.review(question, role)` runs 6
checks before `plan` ever runs: kill switch (`Settings.kill_switch_enabled`), input length
(`Settings.max_question_chars`), injection heuristics (blunt phrasings -- "ignore previous
instructions", "reveal your system prompt" -- least-privilege tools downstream are the real
backstop against anything cleverer), scope (a small set of clearly-not-vendor-procurement
request shapes), rate limit (`RateLimiter`, in-memory per-role sliding window, process-local by
design), and daily spend cap (`SpendTracker`, a role's running spend today, file-backed so it
survives a restart within the same day). Every finding is BLOCK-only (no redact/escalate on the
input side -- there's nothing to partially salvage before a request has even started).
`InputGate.record_spend(role, cost_usd)` is called by `Orchestrator.answer()` after a run
finishes with its real total. `tests/conftest.py`'s autouse `_isolated_spend_log` fixture
points every test's default `InputGate` at a throwaway spend file -- without it, dozens of
orchestrator tests sharing the real on-disk running total tripped the cap for reasons that had
nothing to do with what any individual test was checking (caught and fixed before this shipped).

**Step 7, done:** `LLMClient.complete`/`.structured` -- the one choke point every LLM call
already goes through -- are decorated with `process_inputs=mask_run_payload,
process_outputs=mask_run_payload` (`copilot.guardrails.trace_masking`). Two things ruled out a
`langsmith.Client(anonymizer=...)` threaded through every call site instead, both confirmed with
throwaway scripts before choosing this: constructing a `Client()` eagerly calls `GET /info` over
the network (bad to do just to attach an anonymizer), and setting a masked client as langsmith's
own default via its `contextvars`-based context doesn't survive crossing into
`_run_specialist`'s `ThreadPoolExecutor` worker thread (confirmed empirically -- a
`ContextVar.set()` in the main thread is invisible there). `mask_run_payload` hides the entire
payload if any Restricted table/view name appears anywhere in it (recursively), otherwise
redacts PII/secrets in every string value -- masking only what's *recorded*, never the real
return value the caller gets back.

**Step 8, done:** `tests/test_privacy_leakage_suite.py` names all 23 cases from both specs and
asserts the real mechanism that catches each one today, running as ordinary `pytest` (no
separate eval harness). Building it surfaced and fixed one real gap: the SQL validator had no
defence against an unbounded cross join (`docs/specs/text_to_sql_safety.md`'s "huge cross join
(denial of service)" row) -- the existing `LIMIT 200` cap bounds the *output*, not the join
computation that produces it. Added `_check_cost_limit` (`sql_cost_limit`): blocks a join with
no `ON`/`USING` condition *unless* `WHERE` references columns from at least two of the joined
tables by their table-qualified name -- verified against the real golden set first (`gq-025`'s
genuine self-join, bounded entirely through `WHERE` with no join key, correctly still passes).

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 33 | 440 | `uv run pytest -q`; +12 `copilot.llm`, +12 prompts + `InsightService`, +29 SQL validator, +16 schema/examples/text-to-SQL service, +22 evaluators/langsmith_sync, +10 golden v2, +4 effort lab, +5 tokenization lab, +3 evaluator column-name fix, +10 rag corpus, +9 chunking, +7 embeddings, +10 store, +12 retrieval (BM25 + RRF), +2 store `where` filter, +10 permission filter, +6 corrective RAG, +19 eval harness (golden/metrics/quality), +12 ml metrics, +10 forecast tool, +12 inventory tools, +12 risk classifier, +6 run-log, +5 model selection agent, +9 model selection eval, +10 agent contracts, +14 agent specialists, +12 orchestrator (plan/fan-out/draft), +2 orchestrator verifier loop, +4 orchestrator budget/checkpoint enforcement, +3 orchestrator wiring, +5 orchestrator golden set, +17 Guardian, +4 PII fallback, +4 canary, +4 audit log, +2 topology/end-to-end Guardian wiring, +8 approval-gate interrupt flow, +3 input-gate orchestrator wiring, +18 input gate, +8 trace masking, +4 SQL cost-limit red-team, +23 privacy-leakage suite |
| Day 6: Verifier redraft loop, real end to end | n/a | 2/2 tests pass: a failing draft redrafts once with the verifier's feedback folded in and then passes; a draft that never passes finalizes anyway after `MAX_VERIFICATION_LOOPS` (2), flagged `verified=False` rather than looping forever | `tests/test_orchestrator.py`; real per-question numbers wait for `scripts/run_orchestrator_golden.py` on your machine |
| Day 6: per-agent budget enforcement, real end to end | n/a | 2/2 tests pass: a specialist that outlives `max_latency_s` becomes `status="failed"` (Orchestrator stops waiting, can't force the thread to stop); a specialist that overruns `max_cost_usd` is downgraded `ok` -> `partial` with the overage named in `gaps` | `tests/test_orchestrator.py` |
| Day 6: SQLite checkpointer, real end to end | n/a | 1/1 test: a run's state is actually queryable from the checkpoint file by `thread_id` afterwards | `tests/test_orchestrator.py` |
| Day 6: 10 multi-hop golden questions (harness only) | n/a | schema + dataset built and tested (10/10 load, each needs >=2 distinct specialists, `inventory_planning` questions all also expect `forecasting_risk` per the planner's own rule) -- **not yet run against the real Orchestrator** | `copilot.evals.orchestrator_golden`, `scripts/run_orchestrator_golden.py` ready for your `ANTHROPIC_API_KEY` |
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
| Model Selection Agent (Day 5 step 6) | n/a | 14/14 tests pass (5 agent + 9 eval harness); no real run this sitting -- no `ANTHROPIC_API_KEY` loaded | reuses `CorrectiveRagService`'s propose/critique/revise/abstain shape; real per-question numbers wait for `scripts/run_model_selection_eval.py` on your machine |
| Guardian (Day 7 steps 1/3/4) | n/a | 17 unit tests + 2 end-to-end (topology, a real restricted-name leak blocked through the full graph); 8 checks, worst-severity-wins, every finding kept in `reason_codes` | deterministic only (no LLM judge) -- the one semantic layer the sprint doc names (an injection *classifier*) is this day's cut-first item, not this check's |
| PII / canary / audit log (Day 7 steps 2/3) | n/a | 4 + 4 + 4 tests pass; Presidio's `AnalyzerEngine` (with the `en_core_web_lg` model) installed and cached without issue this sitting, contrary to the docstring's own stated expectation that it might not | regex fallback still the layer every test (and CI) actually exercises, since Presidio availability varies by environment |
| Action-draft approval gate (Day 7 step 5) | n/a | 8 tests pass: pauses only with a real checkpointer, approve/edit/reject paths, an edit is re-reviewed by the Guardian and caught when it reintroduces a leak, a non-approver role is rejected before the graph is even touched | confirmed `interrupt()`/`Command(resume=...)`'s checkpointer requirement and the `ThreadPoolExecutor`/`contextvars` non-propagation (relevant again in step 7) with throwaway smoke scripts before writing the real wiring |
| Input gate (Day 7 step 6) | n/a | 18 unit tests + 3 orchestrator-wiring tests pass | found and fixed a real test-isolation bug before shipping: the default `InputGate`'s `SpendTracker` persists to a real on-disk file, so dozens of orchestrator tests sharing one `InputGate()` default tripped the daily cap for reasons unrelated to what any one test checked -- fixed with `tests/conftest.py`'s autouse fixture, not by weakening the cap |
| LangSmith trace masking (Day 7 step 7) | n/a | 8 tests pass | chose `@traceable(process_inputs=..., process_outputs=...)` over a `Client(anonymizer=...)` after two things ruled the latter out (confirmed empirically, not assumed): constructing a `Client()` calls `GET /info` eagerly, and a `contextvars`-based default client doesn't survive into `_run_specialist`'s worker thread |
| 23-case privacy-leakage suite (Day 7 step 8) | n/a | 23/23 pass | surfaced a real, previously-unguarded gap (an unbounded cross join) rather than just re-testing what already existed; fixed in the SQL validator, verified against the real golden set (`gq-025`) before shipping so the fix doesn't regress a legitimate query |

## Decisions

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot ·
ADR-003 EC2 + Compose runtime · ADR-004 secrets in SSM, OIDC for CI · ADR-005: direct Anthropic
API, not Bedrock, for now -- and the temperature/effort correction above. No new ADR for Day 4 --
the embedding model (local sentence-transformers), vector store (Chroma), the RRF fusion
constant (k=60, Cormack et al. 2009), the Corrective RAG loop's no-web-search simplification
(follows from ADR-002, not a new decision), and building the Ragas-reduced quality evaluators
by hand instead of the `ragas` package (follows the pattern `copilot.evals.evaluators` already
set in Day 3) all just follow already-made or already-standard choices rather than being a new
build-vs-buy decision with real alternatives measured against it. No new ADR for Day 6 either --
the Verifier/budget-enforcement/checkpointer/LangSmith-tagging choices all follow the shape
`ModelSelectionAgent` and `LLMClient` already established (propose/critique/revise, `effort`
over `temperature`, `@traceable`); the one new dependency, `langgraph-checkpoint-sqlite`, is a
companion package to the already-adopted `langgraph`, not a build-vs-buy decision of its own.
**ADR-006 (Guardian design) is Day 7's required ADR per Addendum A1 and is still open** --
I implemented using my own proposed defaults for its 4 questions (outcome severity ordering,
ESCALATE-with-no-reviewer-yet behaviour, vendor-audience check scope, raw-row-shape detection
approach), stated as proposals throughout the code's own docstrings, not as settled decisions.
The template + questions are below; **your answers, not mine, are what the actual ADR-006
document needs to say** -- see "Next step".

## Costs to date

AWS $0, domain $0, LLM ~$0.01 (one real call, 14 Oct, on your machine with your dev key --
`InsightService` on DIAGEO, after fixing a `max_tokens` bug that had been doubling the cost via
unnecessary repair-loop retries). Expected once Day 2 resources exist: about $22 per month on
AWS (Mumbai). Day 6's own real-key run (`scripts/run_orchestrator_golden.py`, 10 multi-hop
questions, each 2-4 specialist LLM calls plus a plan/draft/verify call per question, with up to
2 redrafts) hasn't been run yet -- expect a similar order of magnitude to the effort lab's
~$0.11 for 15 calls, scaled up for more calls per question. Day 7 added $0 -- every Guardian/
input-gate/trace-masking/privacy-suite test is deterministic (no LLM call, no API key), same
posture every other guardrail-layer test in this project takes; Presidio's spaCy model download
also added $0 (no API key needed for that).

## Live URLs

None yet. Target: `https://api.vendor.<domain>/health`.

## Next step

**You: ADR-006 (Guardian design) needs your answers, not mine** -- the template and 3-5 pointed
questions are in this handoff/the chat; Addendum A1's process is I give the template + questions,
you write the answers in your own words, I review/challenge, you revise. I implemented Day 7
using my own proposed defaults (stated as proposals throughout the code's docstrings, e.g.
`guardian.py`'s `_check_vendor_audience`/`_check_grounding`), but the actual ADR-006 document
isn't written until you answer -- this is the one thing blocking Day 7's doc/commit step from
being fully done. Me: once you answer, I'll write ADR-006 from your answers (not mine), finish
the commit, and start Day 8 on your go-ahead. Day 7 itself is complete -- all 8 steps built
(injection classifier cut-first per the sprint doc), 440/440 tests passing, ruff/mypy clean.
Carried forward, still open and not urgent: `scripts/run_orchestrator_golden.py` (Day 6's
10-question real-key run), `scripts/train_risk_classifier.py` against your real
`vw_PortfolioHealth` export, `scripts/run_model_selection_eval.py`, `scripts/build_rag_index.py`
+ `scripts/run_rag_eval.py`, a third re-run of `scripts/run_effort_lab.py`, a real
`TextToSqlService` call, Docker Desktop install/engine status, AWS resources, domain, GitHub
variables from Day 2.
