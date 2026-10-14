# Project Progress: Vendor Intelligence Copilot

Last updated: Wed 14 Oct 2026 (Day 3 of the 10-day sprint, sprint plan v3, in progress)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | Build done; repo pushed to GitHub (14 Oct) |
| 2 | Production skeleton live | Code done and tested. Waiting on you: AWS resources, domain, GitHub variables |
| 3 | LLM service, text-to-SQL, effort and tokenization labs | Build done: 8 of 9 steps shipped (step 7 skipped, see below) |
| 4 | RAG and advanced RAG | Not started |
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

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 33 | 145 | `uv run pytest -q`; +12 `copilot.llm`, +12 prompts + `InsightService`, +29 SQL validator, +16 schema/examples/text-to-SQL service, +22 evaluators/langsmith_sync, +10 golden v2, +4 effort lab, +5 tokenization lab |
| Golden questions | 40 (27 dev, 10 test, 3 adversarial) | 46 (27 dev, 16 test, 3 adversarial) | golden v2 adds the 6 text-to-SQL trap questions from the spec; v1 stays frozen at 40 for history |
| Execution accuracy, grounding, leakage rate | n/a | evaluators built + tested; no end-to-end run yet | `copilot.evals.evaluators.execution_accuracy`/`leakage_free`, 17 tests pass; running them against real `TextToSqlService` output needs your API key, same as the effort/tokenization labs |
| SQL validator: structural + semantic + coverage rules | n/a | 29/29 tests pass, 0 false positives on 33 real golden queries | every trap in `docs/specs/text_to_sql_safety.md`'s trap table has a BLOCK test and an ALLOW test |
| Text-to-SQL self-correction loop | n/a | 4/4 tests pass (first-try, 1-retry, abstain, exhausted) | validator rejection fed back as the next turn; abstains after 2 retries rather than run bad SQL |
| LLM client: retries, repair loop, caching, no-temperature guard | n/a | Tested | against a fake SDK, no API key used (`tests/test_llm_client.py`) |
| First real LLM call (`InsightService`, DIAGEO, viewer role) | n/a | $0.01127, 7.31s, 1 attempt, 0 repairs | run on your machine, 14 Oct; caught and fixed a `max_tokens` truncation bug (see BUILD_LOG) |
| Tokenization lab: provider vs. tiktoken vs. HF, cost/1000 req | n/a | provider 1889.2 tok avg; tiktoken -41.5% (1092.2); HF gpt2 -32.6% (1252.8); $/1000req: $5.28 / $3.68 / $4.01 | run on your machine, 14 Oct; both local tokenizers would make you underestimate the real cost by a third to over 40% |
| Effort lab real sweep (3 questions x 5 effort levels) | n/a | $0.11408 total; exec_acc = 0.67 at every effort level (same question failing each time -- being investigated) | run on your machine, 14 Oct; caught a second `max_tokens`-truncation case (`text_to_sql` prompt, `800 -> 1500`), same bug shape as the InsightService one above |

## Decisions

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot ·
ADR-003 EC2 + Compose runtime · ADR-004 secrets in SSM, OIDC for CI · **ADR-005 (new, 14 Oct):
direct Anthropic API, not Bedrock, for now -- and the temperature/effort correction above.**

## Costs to date

AWS $0, domain $0, LLM ~$0.01 (one real call, 14 Oct, on your machine with your dev key --
`InsightService` on DIAGEO, after fixing a `max_tokens` bug that had been doubling the cost via
unnecessary repair-loop retries). Expected once Day 2 resources exist: about $22 per month on
AWS (Mumbai).

## Live URLs

None yet. Target: `https://api.vendor.<domain>/health`.

## Next step

Me: one open thread from today's real runs -- the effort lab's `exec_acc` came back `0.67`
at every effort level (identical 5 times), which points at one specific question failing
every time rather than randomness. Already fixed one likely cause (`text_to_sql` prompt's
`max_tokens` was `800`, too tight at higher effort -- raised to `1500`, same bug shape as the
`vendor_insight` fix on 13 Oct) and added a per-question breakdown to
`scripts/run_effort_lab.py`'s output so the next run names the exact question. Waiting on
you to re-run it (same ~$0.11) so we can confirm the fix and see which question it was.
After that: Day 4 (RAG and advanced RAG) whenever you're ready to continue the sprint.
You: `git pull`, then `uv run python scripts/run_effort_lab.py` again and paste back the new
per-question table. Two scripts from the previous batch are still outstanding too --
`scripts/push_golden_to_langsmith.py` and `scripts/run_tokenization_lab.py` are both done
(results logged above); only a real `TextToSqlService` call (same pattern as the
`InsightService` first-call test) hasn't been run yet, if you want that logged too. Also
still open: Docker Desktop install/engine status (Day 2's actual `docker build` has not run
yet), and AWS resources, domain, GitHub variables from
Day 2.
