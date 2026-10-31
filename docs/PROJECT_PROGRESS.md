# Project Progress: Vendor Intelligence Copilot

Last updated: Wed 28 Oct 2026 (Day 10, end of the 10-day sprint -- all ten days closed out.
Repo is public, CI green, tags `v0.1.0` and `v0.1.1` pushed (v0.1.1 points at 584d79f; the README
intro rewrite c575916 landed one commit after it and ships in the next release). Left for you:
record the demo, add the GitHub About text and topics, pin the repo, run the real-key scripts,
write ADR-008, send applications. Full close-out in `docs/SPRINT_REPORT.md`.
The depth track starts next, scheduled in that report)

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
| 8 | Product, API keys, latency budget, evals in CI, release v0.1 (Addendum A2 §1) | **Build done: 7 of 7 steps shipped**; `v0.1.0` tagged |
| 9 | Fine-tuning benchmark and MCP (MCP never cut) | **Build done: 6 of 6 steps shipped.** Step 1 (SQL pair generator) and step 4 (MCP server) done and run for real; steps 2-3 and 5-6 (Colab QLoRA fine-tune, base/few-shot/QLoRA comparison, results table + ADR) retrained for real on Colab's T4 after fixing four bugs -- see `docs/BUILD_LOG.md`'s 25-26 Oct entries. **ADR-007: adopt, conditionally** (validate against a broader question set before replacing the frontier-API call in production) |
| 10 | Package and launch the job campaign | **Build half done** (27 Oct): README re-checked and corrected, case-study page published, Code Map page regenerated for Days 1-10, Progress Tracker Sprint tab, version 0.1.1, `docs/SPRINT_REPORT.md`. Career half prepared: 4 CV variants, interview kit, 13-role shortlist. Repo made public and `v0.1.1` tagged (28 Oct). Yours: record demo, About text and topics, pin repo, real-key runs, ADR-008, send applications |

## Day 3 checklist (sprint doc v2/v3 D3)

| # | Item | Status |
|---|---|---|
| 1 | LLM client wrapper (retries, timeouts, caching, `@traceable`, TTFT/latency/tokens/cost) | **Done** |
| 2 | Prompts as versioned YAML; Pydantic outputs with forced tool call and repair retry | **Done** (`copilot.llm.prompts`, `prompts/vendor_insight/v1.yaml`; repair loop was already in the client) |
| 3 | Refactor `vendor_insights.py` into `InsightService` | **Done** (`copilot.insights.service.InsightService`; model id now lives only in the prompt YAML) |
| 4 | Text-to-SQL: schema linking, business rules, 3 retrieved golden examples | **Done** (`copilot.sql.service.TextToSqlService`, `copilot.sql.schema`, `copilot.sql.examples`) |
| 5 | Layered sqlglot validator + `policies/sql_rules.yaml` | **Done** (`copilot.sql.validator`; built ahead of step 4 since step 4's self-correction loop needs it; a 6th layer, data-coverage, was added while building step 4) |
| 6 | Golden v2 as a LangSmith dataset + evaluators | **Done** (`copilot.evals.evaluators`, `copilot.evals.langsmith_sync`; actual push needs your `LANGSMITH_API_KEY` -- run `scripts/push_golden_to_langsmith.py` on your machine) |
| 7 | Question->SQL pair generator | **Done, as Day 9 step 1** (`copilot.sql.pair_generation`; real run on 22 Oct: 1016 candidates, 0 execution failures, 0 validator failures, sampled to 400 -- `evals/datasets/sql_pairs_v1.jsonl`) |
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
| 2 | SKU risk classifier: sklearn Pipeline (Random Forest), leakage-safe features, calibration, SHAP | **Done, real numbers run against `vw_PortfolioHealth` (17 Oct)** (`copilot.ml.risk_classifier`) -- see below |
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

## Day 8 checklist (sprint doc v3 D8, plus Addendum A2 §1)

| # | Item | Status |
|---|---|---|
| 1 | A2 §1.1/§1.5: fallback model on primary-model exhaustion; prompt/model version pinned into every trace | **Done** (`copilot.llm.client.LLMClient`; `CallMetrics.prompt_name`/`.prompt_version`) |
| 2 | A2 §1.2: graceful degradation when a narration call fails | **Done** (`InsightService.vendor_insight`: degrades to the real computed numbers + `narration_available=False` rather than a 500; retries/backoff/jitter and per-agent timeouts were already in place from Day 3/Day 6) |
| 3 | `/ask` FastAPI endpoint, streamed over SSE | **Done** (`Orchestrator.stream_answer()`, `copilot.api.main._sse_lines`) |
| 4 | Invite-code + API-key auth; A2 §1.6 per-user/per-IP rate limiting + per-identity daily budget | **Done** (`copilot.api.auth.AuthStore`; `copilot.api.rate_limit`; `copilot.api.dependencies.enforce_rate_limits`) |
| 5 | A2 §1.7 determinism note | **Done** (`docs/determinism.md`) |
| 6 | Postgres for checkpoints, selectable by settings, local SQLite kept for dev/tests | **Done** (`Orchestrator(checkpointer=...)`; `copilot.api.dependencies._build_checkpointer`; `infra/local/compose.yaml`) -- **not verified against a live Postgres in this environment** (no Docker daemon here); see the two caveats under "Next step" |
| 7 | A2 §1.3 CI eval gate: deterministic-first, `evals/thresholds.yaml`, per-run LLM budget cap | **Done** (`scripts/run_eval_gate.py`, `.github/workflows/ci.yml`'s `eval-gate` job); verified both that it passes cleanly here and that it correctly fails on an injected regression |
| 8 | Minimal UI: chat, agent status, citations, approvals panel, pending-review badge | **Done** (`src/copilot/api/static/`); building it surfaced a real gap -- `Orchestrator.resume_approval()` (Day 7) had no HTTP route at all, so `POST /ask/approve` was added alongside it |
| — | ADR-006 (Guardian design), carried over from Day 7 | **Resolved** in a prior sitting -- your answers to the 4 questions are reflected in `docs/adr/006-guardian-design.md` and the Guardian's own behaviour; no longer open |

**Step 1-2, done:** `LLMClient` routes one more attempt to `Settings.fallback_model` (default
`None` -- no fallback, so a primary-model outage still surfaces as an error exactly as before
this existed) only after the primary model's own retry budget is exhausted, and tags every
`CallMetrics` with `prompt_name`/`prompt_version` so a quality shift is traceable to an exact
prompt file version, not a shrug. `InsightService.vendor_insight` now catches a narration-call
failure and returns the real, already-computed numbers with `narration_available=False` instead
of a 500 -- a new test (`test_vendor_insight_degrades_gracefully_when_narration_fails`) drives 4
real tenacity retry attempts with `time.sleep` patched out, confirming the degrade path is
actually reached, not just written.

**Step 3, done:** `answer()` is now a two-line wrapper around a new `stream_answer()` generator
-- the input-gate check, the graph run (`self._graph.stream(..., stream_mode="updates")`), the
`__interrupt__` detection, and `InputGate.record_spend` all moved there, unchanged, so there's
exactly one copy of that logic. Confirmed with a throwaway probe script, not assumed, exactly
how `stream_mode="updates"` reports node execution and interrupts before committing to the
design. `/ask` forwards one `StreamEvent` per server-sent event.

**Step 4, done:** invite codes and API keys are both `secrets.token_urlsafe(24)`, SHA-256
hashed before ever touching disk, file-backed (`data/auth/auth_store.json`, gitignored) --
the same "small JSON file, loaded fresh, hashed secrets" shape `SpendTracker` already
established, reused rather than reinvented. Per-user/per-IP limits (`RequestRateLimiter`, the
exact sliding-window mechanism `InputGate`'s own `RateLimiter` already uses) and a per-identity
daily budget run *after* auth resolves a `Principal` and *before* the Orchestrator -- or even
the input gate -- ever sees the request.

**Step 5, done:** `docs/determinism.md` draws the same deterministic/non-deterministic line
the eval gate is built on and explains what each existing mechanism (forced structured output,
the repair/redraft loops, the Guardian's unconditional run, golden-set numeric tolerance, prompt
version pinning) does and doesn't do about LLM-call variance. Pure documentation.

**Step 6, done, with an honest caveat:** `Orchestrator.__init__` gained an optional
`checkpointer: BaseCheckpointSaver[str] | None` parameter (any pre-built checkpointer; takes
priority over `checkpoint_path`), kept storage-agnostic -- the module still never imports
`psycopg`. `copilot.api.dependencies._build_checkpointer()` picks a `PostgresSaver` over a
`psycopg_pool.ConnectionPool` (safe for concurrent `/ask` requests, unlike a single
`Connection`) when `Settings.checkpoint_database_url` is a real DSN, and falls back to the
existing local `SqliteSaver` otherwise -- including the same empty-string-env-var guard the
eval gate already needed for `ANTHROPIC_API_KEY`. **No Docker daemon was available in this
environment to run `infra/local/compose.yaml` and prove the Postgres branch against a real,
live database** -- it's covered by unit tests (a real priority test with two SQLite files, and
`_build_checkpointer`'s three branches via monkeypatched `ConnectionPool`/`PostgresSaver`
fakes) and by inspecting the real `PostgresSaver`/`ConnectionPool` API signatures, not by an
actual round-trip. Treat the first run against that compose file as this path's real first
integration test.

**Step 7, done:** `scripts/run_eval_gate.py` runs the full deterministic test suite first (zero
real LLM calls anywhere in it), tolerant of a fixed, named, auditable 15-test allowlist this
repo's own missing local licensed data always produces; an `llm_judged` layer
(`evals/thresholds.yaml`) runs only when a real `ANTHROPIC_API_KEY` *and* the real
snapshot/Chroma index are both present (never true in this repo's own CI, by the same licence
rule that keeps the snapshot off GitHub), so it correctly, cleanly SKIPs there rather than
fabricating a pass or failing over infrastructure that was never supposed to exist in that
environment. A `_CostTrackingLLMClient` wrapper enforces a hard per-run budget cap. Found and
fixed a real bug before shipping: an unset `ANTHROPIC_API_KEY` GitHub secret resolves to an
empty-string env var, which pydantic-settings reads as `SecretStr("")`, not `None` -- a naive
`is None` check would have missed it. Verified bidirectionally: the gate passes cleanly here
(457 passed / 15 known failures / exit 0 at the time this step shipped, 465/15/exit 0 as of the
Postgres and UI commits after it) *and* correctly fails (exit 1) on an injected real regression.

**Step 8, done:** one static page (`src/copilot/api/static/`), no build step, no framework --
a credentials panel, a chat box, a live agent-status strip built from `StreamEvent(type="node")`
events in the real order the graph reported them, result badges (verified, Guardian
escalated/blocked, pending-review with its `review_id`, pending-approval), a citations section
built entirely from real `AgentResult` fields already on `OrchestratorResult.results` (nothing
invented for the UI), and an approval panel. Building the approval panel surfaced a real gap:
`Orchestrator.resume_approval()` (Day 7 step 5) had no HTTP route at all -- every approval-gate
test had exercised it as a direct Python call, so nothing outside the process could actually
approve, edit or reject a paused Action draft before this step. Added `POST /ask/approve`,
gated by its own `require_role("approver", "admin")` dependency. `/ask`'s SSE stream is parsed
by hand in the page's own JS (`fetch` + `ReadableStream`) because `EventSource` cannot carry a
bearer `Authorization` header.

## Day 9 checklist (sprint doc v3 D9, "fine-tuning benchmark and MCP, MCP never cut")

| # | Item | Status |
|---|---|---|
| 1 | Question->SQL pair generator | **Done, run for real** (`copilot.sql.pair_generation`; 22 Oct: 1016 candidates, 0 execution/validator failures, sampled to 400 -- `evals/datasets/sql_pairs_v1.jsonl`, superseded by v2 below) |
| 2-3 | QLoRA fine-tune of a small open model on the project's own question->SQL pairs | **Done, retrained for real** (`finetuning/day9_qlora_colab.ipynb`; Qwen2.5-1.5B-Instruct, 4-bit NF4 + LoRA r=16/alpha=32, 3 epochs, Colab free T4) |
| 4 | Vendor Analytics MCP server ("never cut") | **Done, run for real** (`copilot.mcp.server`; `tests/test_mcp_server.py`) |
| 5-6 | Base vs few-shot vs QLoRA comparison, results table, ADR | **Done** (`finetuning/eval_compare.py`; `finetuning/results_template.md`; `docs/adr/007-finetuning-outcome.md`, **accepted, conditionally**) |

**Steps 1 and 4, done 22 Oct:** the SQL pair generator and the MCP server were both built and
run for real against the real snapshot the same session the snapshot itself was built -- see
`docs/BUILD_LOG.md`'s 22 Oct entries.

**Steps 2-3 and 5-6, done 25-26 Oct, after fixing four bugs (three in measurement, one real):**
`sql_pairs_v1`'s vendor-casing literals turned out to be unlearnable by design (fixed as
`sql_pairs_v2`, 400 execution-verified pairs, 85/15 split -> 340 train / 60 held-out), the
few-shot baseline was leaking held-out questions into its own retrieval pool, and the SQL
extraction step was gluing trailing model prose onto otherwise-correct SQL. Those three fixed,
the actual training bug surfaced: `MAX_LEN=512` silently truncated away every training
example's SQL answer before it was ever appended, so the first "trained" adapter was a
mathematical no-op (loss `0.000000`, every LoRA `B` matrix still zero). Raised to `MAX_LEN=1024`
and retrained for real in one uninterrupted Colab sitting -- training loss fell from 0.551 to
0.0006 across 66 steps, and the adapter's three sanity-check examples matched ground-truth SQL
word for word before any result was trusted. Full story: `docs/BUILD_LOG.md`'s 25-26 Oct
entries.

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 33 | **531 passed, 0 failed, 0 skipped** (30 Oct, after the ranking check and v3 prompts; 524 after the units and forecast-warning fixes; 515 after the PII fix; 512 on 29 Oct after the fail-closed approval fix; 511 re-verified 27 Oct with the snapshot and `snapshot.duckdb` built; without them, 27 snapshot-dependent tests skip) | `uv run pytest -q`; Day 9 added the MCP server, pair generator and eval-compare tests on top of the list that follows; +12 `copilot.llm`, +12 prompts + `InsightService`, +29 SQL validator, +16 schema/examples/text-to-SQL service, +22 evaluators/langsmith_sync, +10 golden v2, +4 effort lab, +5 tokenization lab, +3 evaluator column-name fix, +10 rag corpus, +9 chunking, +7 embeddings, +10 store, +12 retrieval (BM25 + RRF), +2 store `where` filter, +10 permission filter, +6 corrective RAG, +19 eval harness (golden/metrics/quality), +12 ml metrics, +10 forecast tool, +12 inventory tools, +12 risk classifier, +6 run-log, +5 model selection agent, +9 model selection eval, +10 agent contracts, +14 agent specialists, +12 orchestrator (plan/fan-out/draft), +2 orchestrator verifier loop, +4 orchestrator budget/checkpoint enforcement, +3 orchestrator wiring, +5 orchestrator golden set, +17 Guardian, +4 PII fallback, +4 canary, +4 audit log, +2 topology/end-to-end Guardian wiring, +8 approval-gate interrupt flow, +3 input-gate orchestrator wiring, +18 input gate, +8 trace masking, +4 SQL cost-limit red-team, +23 privacy-leakage suite, +6 LLM client fallback/version-pinning, +1 InsightService graceful degradation, +4 `stream_answer()`, +7 API auth, +5 API rate limit, +6 `/ask`, +4 checkpointer-priority/dependencies, +4 `/ask/approve` + UI serving |
| Day 8: CI eval gate, real run in this environment | n/a | deterministic checks: PASS (465 passed, 15 known failures); `llm_judged` layer: SKIPPED (no `ANTHROPIC_API_KEY` configured here) -- exit 0 both when passing and (verified separately) exit 1 on an injected real regression | `scripts/run_eval_gate.py`; the `llm_judged` layer's real scores still wait for a run on your machine with your key + the real snapshot/Chroma index |
| Day 8: Postgres checkpointer | n/a | branch-selection logic unit-tested (3 tests) and priority-over-sqlite tested end to end against two real SQLite files (1 test); **not run against a live Postgres** | no Docker daemon in this environment; `infra/local/compose.yaml` + `docs/BUILD_LOG.md`'s Day 8 step 7 entry cover exactly what was and wasn't verified |
| Day 8: minimal UI + `/ask/approve` | n/a | 4 new tests: an approver resuming a paused Action draft through `/ask` then `/ask/approve` end to end, a non-approver correctly getting 403, and the static page/script actually served; also smoke-tested by hand against a running server (`curl` on `/`, `/static/*`, `/openapi.json`) | no browser-automation test of the page's JS itself -- the SSE-parsing/approval-panel logic is exercised indirectly, through the HTTP contract it calls, not a headless-browser click-through |
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
| RAG eval harness (Day 4 step 7) | n/a | 19/19 tests pass; 20/20 golden questions verified to resolve to exactly one real chunk against the live corpus; **real embedding-model run (16 Oct, laptop): mean recall@5 = 0.800, MRR = 0.662** over all 20 questions (FakeEmbedder's 0.40/0.258 was noise-level, now superseded); 4 misses (q01, q04, q05, q10) all score 0/0, all 4 traced to ONE root cause (see `docs/BUILD_LOG.md`, 16 Oct): standardized contract boilerplate is near-identical across all 10 vendors within each clause type (payment terms, freight terms, rebate %), so same-clause-type chunks embed to nearly the same vector and semantic retrieval alone can't reliably pick the right vendor | the `--quality` (faithfulness/context_recall) run still needs `scripts/run_rag_eval.py --quality` on your machine (costs real API money) |
| Forecast tool (Day 5 step 1), portfolio, real run | n/a | 22/22 tests pass; real backtest: ETS WAPE 0.1153, MASE 1.516, bias -63,673; naive WAPE 0.1153, MASE 1.516, bias -63,671 (essentially tied -- AutoETS's trend reduces to ~none on this series); naive chosen by WAPE tiebreak | matches the analytics repo's own `forecast_backtest.py` "portfolio naive 11.8%" baseline as a sanity check; full reasoning in `docs/BUILD_LOG.md` |
| Inventory tools (Day 5 step 4), real run from the forecast above | n/a | 12/12 tests pass; real plan (3-month horizon, 1-period lead time, 95% service level, $500/order, $0.50/unit/yr holding): mean demand/period 3,758,005, std dev 363,277, safety stock 597,537, reorder point 4,355,542, EOQ 300,320 | caught and fixed a bug before shipping: std dev must come from historical variability, not variance across a (possibly flat) forecast -- see `docs/BUILD_LOG.md` |
| SKU risk classifier (Day 5 steps 2-3), synthetic fixture run | n/a | 12/12 tests pass; n=2000: RF accuracy 0.834 -> 0.820, F1 0.291 -> 0.211; XGBoost accuracy 0.898 -> 0.886, F1 0.667 -> 0.596 (leaky -> leakage-safe) | leakage inflates both models' scores in the expected direction; `SalesToPurchaseRatio` had to be added to `LEAKING_FEATURES` after it was found reconstructing `ProfitMargin` algebraically -- see `docs/BUILD_LOG.md`. Synthetic data, so direction is the finding, not the exact figures |
| SKU risk classifier, real `vw_PortfolioHealth` run (17 Oct) | n/a | n=10,495 real SKU rows, label balance 0.303; RF accuracy 0.997 -> 0.952, F1 0.994 -> 0.919; XGBoost accuracy 0.999 -> 0.971, F1 0.999 -> 0.953 (leaky -> leakage-safe); leakage-safe top SHAP driver: `StockTurnover` (0.2809), far above the next feature (0.0343) | run via `uv run python scripts/train_risk_classifier.py` against your own SQL Server export; same already-leakage-safe `LEAKING_FEATURES` list diagnosed on synthetic data on 14 Oct, now validated on real data -- no new leakage found, confirms the earlier fix generalizes. These replace the synthetic-fixture numbers above as the reported figures |
| CSV run-log (Day 5 step 5) | n/a | 6/6 tests pass; smoke-tested end to end via `scripts/train_risk_classifier.py` against a synthetic CSV | MLflow cut-first per sprint doc; `run_log.csv` covered by the existing blanket `*.csv` gitignore rule |
| Model Selection Agent (Day 5 step 6) | n/a | 14/14 tests pass (5 agent + 9 eval harness); no real run this sitting -- no `ANTHROPIC_API_KEY` loaded | reuses `CorrectiveRagService`'s propose/critique/revise/abstain shape; real per-question numbers wait for `scripts/run_model_selection_eval.py` on your machine |
| Guardian (Day 7 steps 1/3/4) | n/a | 17 unit tests + 2 end-to-end (topology, a real restricted-name leak blocked through the full graph); 8 checks, worst-severity-wins, every finding kept in `reason_codes` | deterministic only (no LLM judge) -- the one semantic layer the sprint doc names (an injection *classifier*) is this day's cut-first item, not this check's |
| PII / canary / audit log (Day 7 steps 2/3) | n/a | 4 + 4 + 4 tests pass; Presidio's `AnalyzerEngine` (with the `en_core_web_lg` model) installed and cached without issue this sitting, contrary to the docstring's own stated expectation that it might not | regex fallback still the layer every test (and CI) actually exercises, since Presidio availability varies by environment |
| Action-draft approval gate (Day 7 step 5) | n/a | 8 tests pass: pauses only with a real checkpointer, approve/edit/reject paths, an edit is re-reviewed by the Guardian and caught when it reintroduces a leak, a non-approver role is rejected before the graph is even touched | confirmed `interrupt()`/`Command(resume=...)`'s checkpointer requirement and the `ThreadPoolExecutor`/`contextvars` non-propagation (relevant again in step 7) with throwaway smoke scripts before writing the real wiring |
| Input gate (Day 7 step 6) | n/a | 18 unit tests + 3 orchestrator-wiring tests pass | found and fixed a real test-isolation bug before shipping: the default `InputGate`'s `SpendTracker` persists to a real on-disk file, so dozens of orchestrator tests sharing one `InputGate()` default tripped the daily cap for reasons unrelated to what any one test checked -- fixed with `tests/conftest.py`'s autouse fixture, not by weakening the cap |
| LangSmith trace masking (Day 7 step 7) | n/a | 8 tests pass | chose `@traceable(process_inputs=..., process_outputs=...)` over a `Client(anonymizer=...)` after two things ruled the latter out (confirmed empirically, not assumed): constructing a `Client()` calls `GET /info` eagerly, and a `contextvars`-based default client doesn't survive into `_run_specialist`'s worker thread |
| 23-case privacy-leakage suite (Day 7 step 8) | n/a | 23/23 pass | surfaced a real, previously-unguarded gap (an unbounded cross join) rather than just re-testing what already existed; fixed in the SQL validator, verified against the real golden set (`gq-025`) before shipping so the fix doesn't regress a legitimate query |
| Day 9: question->SQL pair generator, real run | n/a | 1016 candidates, 0 execution failures, 0 validator failures, sampled to 400 | `copilot.sql.pair_generation`; `evals/datasets/sql_pairs_v1.jsonl` (v2 fixes an unlearnable vendor-casing pattern in v1) |
| Day 9: Vendor Analytics MCP server, real run | n/a | built and exercised against the real snapshot | `copilot.mcp.server`; `tests/test_mcp_server.py` -- the sprint's "MCP never cut" item |
| Day 9: QLoRA fine-tuning benchmark, real retrained result | n/a | execution_accuracy: qlora 1.0 vs base_zero_shot 0.017 vs base_few_shot 0.1; executable_rate: qlora 1.0 vs 0.25 vs 0.333; mean_latency_s: qlora 4.424 vs 6.764 vs 3.828 (n=60 held-out each) | `finetuning/eval_compare.py`, `finetuning/results_template.md`; first training attempt silently failed (`MAX_LEN=512` truncation, loss stuck at 0.000000) -- these numbers are from the retrained adapter, sanity-checked word-for-word against ground truth before being trusted |
| Day 9: ADR-007, fine-tuning adopt/don't-adopt decision | n/a | **Adopt, conditionally** -- all three decision-framework criteria (accuracy, executable rate, latency) pass clearly on real numbers | `docs/adr/007-finetuning-outcome.md`; the one named condition: validate against a broader, non-template question set before this replaces the frontier-API call in `TextToSqlService`'s primary path -- `sql_pairs_v2` is a fixed template family, so the 1.0 proves that family is learned, not arbitrary generalization |

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
**ADR-006 (Guardian design), Day 7's required ADR per Addendum A1, is resolved** -- your
answers to its 4 questions (outcome severity ordering, ESCALATE-with-no-reviewer-yet behaviour,
vendor-audience check scope, raw-row-shape detection approach) are written into
`docs/adr/006-guardian-design.md` and reflected in the Guardian's actual checks; no longer open,
no further decision needed. **No new ADR for Day 8** -- every Day 8 piece follows an
already-established shape rather than a build-vs-buy decision made among real alternatives
here: `/ask/approve` reuses the `require_role(*allowed)` + `Depends()` pattern `/ask` already
set (Day 8 step 4); the Postgres checkpointer widens `Orchestrator`'s existing "pass in a
storage object, don't build your own" posture (Day 6 step 6) from one concrete type to any
`BaseCheckpointSaver`, with Postgres itself named by the sprint brief, not chosen among
alternatives here; the auth/rate-limit file-backed, hashed-secret shape reuses `SpendTracker`'s
own established pattern; and the UI is a static-files mount, the simplest option for "serve one
page from the same process," not a framework decision with competing options weighed.
**ADR-007 (fine-tuning outcome), Day 9's required decision per the sprint brief, is resolved:**
adopt the QLoRA-tuned model into the production text-to-SQL path, conditionally -- real numbers
clearly pass all three of the decision framework's own criteria (execution accuracy, executable
rate, latency), but the one named condition (validate against question phrasings outside
`sql_pairs_v2`'s fixed template family) is explicitly not yet done, so this is not yet wired into
`TextToSqlService`'s primary path. No other new ADR for Day 9 -- the MCP server follows the
project's own existing service-boundary conventions rather than a build-vs-buy call made fresh
here.

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
also added $0 (no API key needed for that). Day 8 added $0 too -- the auth/rate-limit/SSE/
checkpointer/UI work is all deterministic Python with no API key; the CI eval gate's own
`llm_judged` layer, the one piece of Day 8 that would spend real money, correctly SKIPPED in
this environment rather than running (no `ANTHROPIC_API_KEY` here) -- its real scores still
wait for a run on your machine with your key and the real snapshot/Chroma index. Day 9 added
under $1 total for the real fine-tuning benchmark (Colab's free T4 tier has no compute cost;
the 180 base/few-shot/QLoRA generations for `eval_compare.py` are the only real spend) -- the
MCP server and pair generator added $0 (deterministic / local-model work).

## Live URLs

API: none yet. Target: `https://api.vendor.<domain>/health`.

Shared pages (private until shared from each page's Share menu):

| Page | Link | Source in repo |
|---|---|---|
| Case study | https://claude.ai/artifact/KyLyQ3ywwWjWuXEvKKR1YF | `docs/case-study/index.html` |
| Code Map (Version 9, Days 1-10) | https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA | `docs/code-map/index.html`, built by `scripts/build_code_map_page.py` |
| Plan and Progress Tracker | https://claude.ai/artifact/AYJf5GTMPMdqPoXfcSztA1 | `docs/tracker/index.html` |

## Next step

**Day 8 is build-complete; `v0.1.0` is tagged.** Everything in the Day 8 checklist above is
built, tested (465 passing, same 15 known missing-data failures as every prior day), ruff/mypy
clean, and committed; the sprint brief's own Day 8 scope named "release v0.1.0" as its last
item, so that's done too -- `pyproject.toml` bumped to `0.1.0`, tagged `v0.1.0` on `main`, with
a release note (`git tag -l -n99 v0.1.0`) summarizing what shipped and the two honest caveats
below, rather than claiming a clean bill of health.

What's genuinely left, none of it blocking the tag itself:

1. **Verify the Postgres checkpointer against a real, live Postgres.** Honestly flagged above
   and in `docs/BUILD_LOG.md` -- no Docker daemon in this environment, so this path has unit
   tests and API-signature inspection behind it, not a live round-trip. `infra/local/
   compose.yaml up -d`, set `CHECKPOINT_DATABASE_URL`, run the API, and confirm a checkpoint
   actually lands in that database -- this is the one piece of Day 8 I'd call genuinely unproven
   rather than just "not yet run on your machine for real numbers" (the next item's category).
2. **Real-key runs that only add real numbers to what's already built and tested**, same
   carried-forward category as every prior day: `scripts/run_orchestrator_golden.py` (Day 6's
   10-question real-key run), `scripts/run_eval_gate.py`'s `llm_judged` layer with a real key +
   snapshot + Chroma index, `scripts/run_model_selection_eval.py`, `scripts/
   build_rag_index.py` + `scripts/run_rag_eval.py`, a third re-run of `scripts/
   run_effort_lab.py`, a real `TextToSqlService` call, and a real walkthrough of the new UI
   against the real server (`uv run uvicorn copilot.api.main:app` then open `http://
   localhost:8000/`) -- everything above was smoke-tested against a running server in this
   session, but not by a human clicking through it. (`scripts/train_risk_classifier.py` against
   the real `vw_PortfolioHealth` export is no longer on this list -- run 17 Oct, see the Day 5
   results table above.)
3. **Still waiting on you, carried forward from Day 2, unrelated to Day 8's own code:** Docker
   Desktop install/engine status, AWS resources, domain, GitHub Actions variables -- nothing in
   Day 8 needed these to build or test, but the actual deployed `/health` URL still waits on
   them (see "Live URLs" below).

**Update, 22 Oct, same day as Day 9's build started:** item 2's "real-key runs" is specifically
an `ANTHROPIC_API_KEY` gap, not a data gap -- worth separating those explicitly now that the
data half is resolved. You uploaded `Vendor_Summary.xlsx` directly to the build chat (never
committed to Git -- ADR-002 restricts that, not uploading it to a session), so the real
snapshot was built and verified for real in this cloud session: full suite went from
465 passed/15 known failures to **499 passed/0 failed**, with two canonical numbers
(DIAGEO's $68,739,834.97 revenue, MARTIGNETTI's 31.98% blended margin) spot-checked directly
rather than just trusting the green suite. Everything in item 2 above that only needed data, not
an API key, is now also real rather than smoke-tested -- but every item in that list that also
needs an LLM call (the eval gate's `llm_judged` layer, `run_orchestrator_golden.py`, a real
`TextToSqlService`/`ask_vendor_question` call) still needs `ANTHROPIC_API_KEY`, which this
session still doesn't have -- a credential gap, not a data gap, and the two turned out to be
fully independent of each other.

Day 9 (fine-tuning benchmark + MCP) is now in progress: step 1 (the SQL pair generator) and
step 4 (the Vendor Analytics MCP server, "never cut" per the sprint's own cut-first list) are
both done and run for real against the real snapshot above -- see `docs/BUILD_LOG.md`'s Day 9
entries.

**Update, 23 Oct ("Option A"):** steps 2-3 and 5-6 scaffolded and ready to run, not yet executed
for real -- superseded by the update below.

**Update, 25-26 Oct, Day 9 build-complete:** retrained for real on Colab's free T4, after
finding and fixing four bugs (three in the measurement code, one real training bug that needed
the GPU step rerun -- full story in `docs/BUILD_LOG.md`'s 25-26 Oct entries and the Day 9
checklist above). `docs/adr/007-finetuning-outcome.md` moved from PENDING to **Accepted,
conditionally**: adopt the QLoRA-tuned model, but validate it against a broader, non-template
question set before it replaces the frontier-API call in `TextToSqlService`'s primary path --
that validation is explicitly not done as part of this ADR, and is the one open item carried
forward from Day 9.

**Day 9 is now fully build-complete, all 6 of 6 steps shipped** (MCP server + pair generator
from 22 Oct, fine-tuning benchmark + ADR-007 from 25-26 Oct). Nothing above blocks Day 10.

## Next: Day 10 -- package and launch the job campaign

Per the sprint doc's own D10 section: a build half (~6h -- README with architecture diagram,
agent roster, results table, cost/latency, ADR index, limitations, roadmap; a 3-minute demo
video; a case-study page on your domain, linked from the landing page that was itself deferred
here from Day 2-3; tag `v0.1.1`; a final Daily Sprint Report) and a career half (~5h -- CV
variants for AI Analytics Consultant / GenAI Engineer / Agentic AI Engineer / AI Solutions
Engineer, LinkedIn headline/About/Featured + one architecture post, a 60-second and 5-minute
pitch rehearsed against the sprint doc's 40 Tier-A interview questions, and 15-20 applications
across India/remote/UK/EU) that run in parallel, not sequentially. One standing constraint going
into it: the sprint doc is explicit that the repo can claim "benchmarked a QLoRA fine-tune for
text-to-SQL," not "deployed a fine-tuned model to production," since ADR-007 is
adopt-conditionally, not adopt-and-shipped.

**Update, 27 Oct, Day 10 build half in progress:** confirmed repo state at the start of this
chat (matched the handoff exactly: commit `b4b57f9`'s successor `2e3b0c2`, `v0.1.0` tag present
on origin, 511 passed/0 failed as of the last real run on 26 Oct). `uv sync --frozen` hit the
same infrastructure hiccup the handoff already flagged -- the `download-r2.pytorch.org` CDN host
isn't reachable through this session's proxy -- confirmed non-blocking (same category as every
prior day's environment gap, not a code regression) and not retried further since it doesn't
block Day 10's own scope. Found and fixed one real inconsistency while confirming state: the
handoff's own narrative mentioned an "R13" RAID item that was never actually added to
`docs/RAID.md` -- added now.

Shipped so far: the full README (problem, Mermaid architecture diagram, agent roster incl. the
Model Selection Agent, a results table pulling only real numbers already recorded in this file,
the ADR index, an explicit limitations section, and the roadmap), `docs/DEMO_SCRIPT.md` (timed
3-minute script with a recording checklist), and `docs/CASE_STUDY.md` (case-study page content,
ready to publish once the landing page exists). Still open for the build half: the Code Map
artifact's one-time end-of-sprint update, the Progress Tracker page, tagging `v0.1.1`, and the
final Daily Sprint Report. Career half (CV variants, LinkedIn, pitch rehearsal, applications) not
started yet.

**Update, 27 Oct, Day 10 build half done:** re-verified the suite with the snapshot rebuilt from
the public analytics repo's workbook: 511 passed, 0 failed, 0 skipped (27 tests skip when
`snapshot.duckdb` is absent). Full-history
gitleaks scan clean. Found and fixed: 28 files missing from `docs/CODE_MAP.md` (all of Day 9,
deploy/infra, living docs), a "no latency penalty" claim for QLoRA in the README and case study
(QLoRA is slower than few-shot base: 4.42 s vs 3.83 s), and an overstated background line in
the README. Published the case-study page, regenerated the Code Map page from the markdown
(new `scripts/build_code_map_page.py`), added a Sprint tab to the Progress Tracker, bumped the
version to 0.1.1, wrote `docs/SPRINT_REPORT.md` (final report, ADR-008 questions for you, the
depth-track schedule). **Next:** your items in `docs/SPRINT_REPORT.md` ("Your items, in order"),
then the depth track's first block (close-out: real-key runs, deploy, demo).
