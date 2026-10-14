# Project Progress: Vendor Intelligence Copilot

Last updated: Wed 14 Oct 2026 (Day 4 of the 10-day sprint, sprint plan v3, in progress)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | Build done; repo pushed to GitHub (14 Oct) |
| 2 | Production skeleton live | Code done and tested. Waiting on you: AWS resources, domain, GitHub variables |
| 3 | LLM service, text-to-SQL, effort and tokenization labs | Build done: 8 of 9 steps shipped (step 7 skipped, see below) |
| 4 | RAG and advanced RAG | In progress: 5 of 7 steps shipped |
| 5 | ML tools for the agents | Not started |
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
| 6 | Corrective RAG loop in LangGraph | Not started |
| 7 | 20 labelled questions: recall@5, MRR, Ragas | Not started |

**Cut-first item for step 4:** a cross-encoder reranker on top of the fused BM25+vector
candidates. The step's job was to prove the fusion mechanics (BM25 index, RRF math, candidate
pool sizing) are correct; a reranker is a real quality lever but a second model to load and run
per query, and `RetrievedChunk` already carries the full chunk text so one can be bolted on
later as a third stage without changing `copilot.rag.retrieval`'s contract.

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 33 | 208 | `uv run pytest -q`; +12 `copilot.llm`, +12 prompts + `InsightService`, +29 SQL validator, +16 schema/examples/text-to-SQL service, +22 evaluators/langsmith_sync, +10 golden v2, +4 effort lab, +5 tokenization lab, +3 evaluator column-name fix, +10 rag corpus, +9 chunking, +7 embeddings, +10 store, +12 retrieval (BM25 + RRF), +2 store `where` filter, +10 permission filter |
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

## Decisions

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot ·
ADR-003 EC2 + Compose runtime · ADR-004 secrets in SSM, OIDC for CI · ADR-005: direct Anthropic
API, not Bedrock, for now -- and the temperature/effort correction above. No new ADR yet for
Day 4 -- the embedding model (local sentence-transformers), vector store (Chroma), and the RRF
fusion constant (k=60, the standard default from Cormack et al. 2009) all just follow
already-named/standard choices rather than being a real build-vs-buy decision with alternatives
measured against it.

## Costs to date

AWS $0, domain $0, LLM ~$0.01 (one real call, 14 Oct, on your machine with your dev key --
`InsightService` on DIAGEO, after fixing a `max_tokens` bug that had been doubling the cost via
unnecessary repair-loop retries). Expected once Day 2 resources exist: about $22 per month on
AWS (Mumbai).

## Live URLs

None yet. Target: `https://api.vendor.<domain>/health`.

## Next step

Me: continuing Day 4 build -- steps 6-7 next (the Corrective RAG loop in LangGraph, and the
recall@5/MRR/Ragas eval on 20 labelled questions). You: run
`scripts/build_rag_index.py` on your machine whenever convenient to get the real embedding
index built (needs no API key, just internet access for the one-time model download) -- not
blocking, step 4's retrieval-quality work can be developed and tested against FakeEmbedder in
the meantime, same as the rest of Day 4 so far. Also still open, carried from earlier days and
not urgent: a third re-run of `scripts/run_effort_lab.py` for a clean accuracy number; a real
`TextToSqlService` call; Docker Desktop install/engine status (Day 2's actual `docker build`
has not run yet); AWS resources, domain, GitHub variables from Day 2.
