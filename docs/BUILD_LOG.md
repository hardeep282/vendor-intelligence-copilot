# Build Log

## 2026-10-10 · Day 1 · Foundations, data, golden set

**Covered:** repo layout and tooling; disclosure policy; licence-safe snapshot; 40-question golden set; living docs.

**Decisions:** ADR-000 (prompt corrections), ADR-001 (separate repo), ADR-002 (vendor-level snapshot, never committed).

**Mistakes and fixes:**
- `uv sync` failed because `pyproject.toml` named a `README.md` that did not exist yet. Fixed by creating a short README first.
- Excel sheet `vw_PortfolioHealth ` has a trailing space in its name. The snapshot builder strips names before lookup.
- mypy flagged `str.strip` on sheet names typed `int | str`. Fixed with `str(s)`.
- `ruff` flagged long lines in the golden-set builder and `zip` without `strict=`. Fixed by a scoped ignore and `strict=True`.

**Metrics:** 17 tests pass; snapshot totals match the canonical metrics (see PROJECT_PROGRESS.md). Revenue from the monthly-demand table is $452.06M versus $451.62M from the vendor views (RAID R6).

**Costs:** $0.

**Open:** accounts checklist (domain, AWS, LangSmith); push the repo; resolve RAID R1.

## 2026-10-13 · Day 2 · Production skeleton (code side)

**Covered:** FastAPI `/health` and `/version`; SSM secrets loader; multi-stage non-root Dockerfile;
compose stack; EC2 bootstrap; deploy script with health-checked rollback; GitHub Actions CI (lint,
types, tests, gitleaks, image smoke test) and an OIDC-based deploy job; IAM policies; sprint v2
additions to Day 1 (gitleaks pre-commit, dev/prod key policy).

**Decisions:** ADR-003 (EC2 t3.small + Compose + host nginx/Certbot), ADR-004 (SSM secrets, OIDC CI,
branch-scoped trust instead of GitHub Environments). Landing page moved to Day 10.

**Mistakes and fixes:**
- Starlette warned that `httpx` with its TestClient is deprecated; switched the dev dependency to `httpx2`.
- A test set environment variables directly, which would have leaked into later tests; it now uses
  `monkeypatch.setenv` first so pytest restores the environment.
- shellcheck flagged unused loop variables in the workflow (`i`); renamed to `_`.
- First draft trusted the GitHub `production` environment; changed to the `main` branch because
  environments in private repos depend on the GitHub plan.
- The Docker image could not be built in the build workspace (registries blocked). Verified instead by
  installing with `--frozen --no-dev` in a clean folder and serving both endpoints; the real image is
  built and smoke-tested by the CI `image` job on every push.

**Metrics:** 22 tests pass; ruff, mypy, actionlint, shellcheck and gitleaks clean.

**Costs (expected, Mumbai, 24/7):** t3.small $0.0224/h ≈ $16.35; public IPv4 $0.005/h ≈ $3.65;
gp3 20 GB × $0.0912 ≈ $1.82; Route 53 zone $0.50; ECR storage ≈ $0.03 → about $22.35 per month.
EC2 and EBS rates are from a third-party price list (aws-pricing.com); IPv4, Route 53 and ECR from AWS pages.

**Open:** AWS resources, GitHub variables, domain and HTTPS (all on the Day 2 guide).

## 2026-10-13 · Review fixes before Day 3

**Covered:** external review of the text-to-SQL plan; master prompt corrections (v2.7); DuckDB hardening.

**Decisions:** layer 0 of SQL safety built now, because it is data-layer work and cheap: the snapshot is served from
a read-only `snapshot.duckdb` with `enable_external_access=false` and `lock_configuration=true`. Spec for layers 1–4
and the Day 7 red-team cases in `docs/specs/text_to_sql_safety.md`.

**Review points checked against the data:**
- Freight: `SUM` across vendor-level freight is correct ($1.64M); the real trap is a fan-out join ($19.68M).
- Margins: `AVG(BlendedMarginPct)` = 5.31% vs ratio of sums 28.72% (all rows).
- Coverage: `SalesYear = 2025` returns 0 rows.
- Injection: a `system_users` table does not exist; the real DuckDB surface is table functions, ATTACH, COPY,
  INSTALL and SET, all now refused by the engine.

**Metrics:** 33 tests pass (11 new attack tests).

## 2026-10-14 · Day 3 step 1 -- LLM client wrapper

**Covered:** `copilot.llm` package: pricing table (`pricing.py`), typed call results
(`types.py`), and `LLMClient` (`client.py`) with retries+backoff, timeouts, prompt caching,
`@traceable`, per-call TTFT/latency/token/cost logging, and a native structured-output path
(`output_format=<PydanticModel>`) with a one-repair self-correction loop.

**Decisions:** ADR-005 (direct Anthropic API, not Bedrock, for now).

**Correction found and carried forward (checked against the installed SDK, anthropic==1.13.0,
and Anthropic's Sonnet 5.5 migration guide, both 14 Oct 2026):** `temperature`, `top_p` and
`top_k` are not accepted by this model generation's Messages API at all -- a non-default value
returns HTTP 400. `LLMClient.complete`/`.structured` take `effort` instead
(`output_config.effort`: low/medium/high/xhigh/max). **This changes B1 step 8 for later today:**
the sprint's "temperature lab" becomes an **effort lab** (same metrics, `effort` swept instead
of `temperature`) -- flagged to the user before building it, not discovered after a 400.
Full reasoning in `docs/adr/005-llm-provider.md`.

**Mistakes and fixes:**
- A stray, untracked `data/snapshot/snapshot.duckdb` was present in the fresh clone (pre-dates
  this session; not something `git clone` could have produced from a git-ignored path). Deleted
  it before building, since `copilot.data.store.connect()` silently reuses a stale `.duckdb` and
  its `lock_configuration=true` then blocks the exact `SET` calls meant to protect a *fresh* one
  -- that was the actual cause of 13 test failures before the real snapshot was built.
- First draft of the retry loop closed over the `for repair_attempt in ...:` loop variable from
  inside a nested function (ruff B023): fixed with default-argument capture
  (`def _call(_repair: int = repair_attempt)`), which also reads correctly under tenacity's retry
  wrapper since defaults bind once, at definition time.
- `mypy --strict` flagged the tenacity-decorated inner `_call` as "untyped decorator"; traceable
  needed no such ignore once `self` was dropped from its typed surface -- only `@_retrying()`
  needed `# type: ignore[untyped-decorator]`.

**Tests added:** `tests/test_llm_client.py` (12 cases against a hand-written fake Anthropic
streaming client in `tests/fakes/anthropic_fakes.py` -- no network, no API key) and
`tests/test_llm_pricing.py` (4 cases). Covers: happy path metrics, prompt-caching block,
the no-temperature regression guard, `effort` wiring, retry-then-succeed, give-up-after-4,
no-retry-on-400, structured happy path, one successful repair, and give-up-after-repairs.

**Metrics:** 47 tests pass (was 33); ruff, mypy --strict, ruff format all clean.

**Dependencies added:** `anthropic>=0.75.0`, `langsmith>=0.3.0`, `sqlglot>=27.0.0`,
`tenacity>=9.0.0`, `tiktoken>=0.9.0` (sqlglot/tiktoken are ahead of this step; added together
so Day 3's later steps don't need a second `uv sync`).

**Open:** steps 2-9 of Day 3 (prompts as YAML, InsightService, text-to-SQL + validator, golden
v2, pair generator, effort lab, tokenization lab) -- not started yet this session.

### Day 3, step 2-3: prompts as versioned YAML; `InsightService` (14 Oct, same session continued)

**Covered:**
- `prompts/<name>/v<N>.yaml` on disk, `copilot.llm.prompts.load_prompt()` to read and validate
  one (model id, `max_tokens`, `effort`, `cache_system`, system/user text all in the file, not
  in Python). `Prompt.render_system()/.render_user()` do plain `str.format()` substitution.
  A behaviour change is a new version file, not an edit to an existing one, so eval history
  stays attached to the version that produced it. First prompt written: `vendor_insight/v1.yaml`.
- `copilot.insights.service.InsightService` -- the refactor target named in ADR-000 item 5
  (legacy `vendor_insights.py`, hardcoded `claude-opus-4-5`). `vendor_insight()` joins the three
  `internal`-class source tables (`vendor_revenue_summary`, `vendor_tiering`,
  `vendor_profit_leakage`) by vendor name, masks any field whose row fails the caller's
  k-threshold (`disclosure.yaml`'s `MeetsMinK`) as `{"withheld": ...}` rather than dropping it
  silently, and calls `LLMClient.structured()` with a forced `VendorInsight` Pydantic model
  (`headline`, `narrative`, `key_metrics_cited`, `risk_flags`) so every number in the output
  traces to a named input field. Unknown vendor raises `VendorNotFoundError` before any LLM call.
- Model id is now entirely config (the prompt YAML's `model:` field) -- no model string appears
  in `copilot.insights.service` at all, closing out ADR-000 item 5.

**Tests added:** `tests/test_prompts.py` (6 cases: load latest/explicit version, missing
name/version, system/user substitution) and `tests/test_insight_service.py` (6 cases: full data
for an ungated role, withheld-below-k for a gated role, below-k still shown to an ungated role,
unknown vendor raises, a full `vendor_insight()` call against an in-memory DuckDB + the same
fake Anthropic stream used in `test_llm_client.py`, and unknown vendor never reaching the LLM).

**Metrics:** 59 tests pass (was 47); ruff, mypy (29 source files), ruff format all clean.

**Open:** steps 4-9 of Day 3 (text-to-SQL schema linking + layered sqlglot validator +
`policies/sql_rules.yaml`, golden v2 as a LangSmith dataset, question→SQL pair generator, the
effort lab, the tokenization lab).

### First real LLM call (14 Oct, your machine, your dev key)

`InsightService.vendor_insight("DIAGEO NORTH AMERICA INC", role="viewer")` -- the first live
Anthropic call this project has made. Caught a real bug on the first try: `max_tokens: 700` in
`prompts/vendor_insight/v1.yaml` was too small for the full `VendorInsight` payload (18 cited
fields + narrative + 3 risk flags), so the model's JSON got cut off mid-string
(`EOF while parsing a string at ... column 1504`). `LLMClient.structured()`'s repair loop caught
it and retried successfully -- so the call still returned a valid, well-grounded insight -- but
at 2x the cost and latency of one clean call. Fixed by raising `max_tokens` to 1200 in the same
file (not a new version: this is a capacity correction, not a change to the prompt's behaviour,
tone or output shape -- the rule in `copilot.llm.prompts`'s docstring about versioning is for the
latter). Tests unaffected (none assert `max_tokens`, by design).

The insight itself was well-grounded on the first full read: every number in the narrative
traced to a field in `key_metrics_cited`, and `risk_flags` (dead stock, excise leakage,
loss-making SKUs) matched what the leakage figures actually showed -- no invented numbers, no
generic risk language.

**Confirmed fixed:** same call re-run after pulling the `max_tokens: 1200` fix and restarting
the Python process (prompts are `@cache`d per-process, so the edited YAML needs a fresh
interpreter to take effect) -- `repair=0 attempt=1`, clean single call, `cost=$0.01127`,
`latency=7.31s`. First clean baseline numbers for the DIAGEO vendor-insight call.

| Run | max_tokens | Attempts | Repair | Cost | Latency |
|---|---|---|---|---|---|
| Before fix | 700 | 2 (truncated, then repaired) | 1 | not captured | not captured |
| After fix | 1200 | 1 | 0 | $0.01127 | 7.31s |

## 2026-10-14 · Day 3, step 5 · Layered sqlglot validator + `policies/sql_rules.yaml`

**Covered:** `copilot.sql.validator.validate()` -- the static check every LLM-generated SQL
string passes through before it ever reaches `copilot.data.store` (layer 0). Built the two
layers the spec calls for:

- **Layer 1 (structure):** exactly one statement; root is SELECT/UNION/EXCEPT/INTERSECT; every
  real table in every branch (CTEs, joins, subqueries, UNION arms) is in `disclosure.yaml` *and*
  readable by the caller's role; no table-valued functions (`read_csv`, `glob`, `duckdb_tables`,
  `pragma_*`); no `information_schema`/`pg_catalog`; no `PRAGMA`/`ATTACH`/`SET`/`COPY`/`INSTALL`/
  `LOAD`/`CALL` statements; `LIMIT` injected at 200 if missing, or lowered to 200 if higher.
- **Layer 2 (semantic traps, `policies/sql_rules.yaml`):** `AVG`/`SUM` of an already-blended
  column (`BlendedMargin`, `SharePct`, ...) across rows is blocked -- a portfolio figure must be
  a ratio of sums; `SUM` of a per-vendor total (`TotalFreight`, `TotalRevenue`, ...) after a join
  that touches a fan-out table (`vendor_monthly_demand`, one row per vendor per month) with no
  `GROUP BY` is blocked -- the join repeats each vendor's row once per month before the sum ever
  runs; adding two independent SKU-classification counts in one expression
  (`LossMakingSKUs + DeadStockSKUs`) is blocked -- the dimensions overlap, so the two columns
  must be reported separately.

Every one of the six RAID-flagged traps in `docs/specs/text_to_sql_safety.md`'s "Why this
exists" table now has a test that proves the validator catches it, plus the matching "this
correct form is allowed" test so the rule doesn't over-block.

**Mistakes and fixes:**
- First cut of `_function_name()` used `exp.Anonymous.sql_name()` to recover a blocked
  function's real name (`duckdb_tables`, `glob`, ...). sqlglot's `sql_name()` returns the
  literal string `"ANONYMOUS"` for that node type -- it's a generic dispatch name, not the
  parsed function name -- so `duckdb_tables()` silently passed validation. Fixed by reading
  `.this` directly on the `Anonymous` node, which holds the actual called name as parsed from
  the SQL (confirmed interactively: `t.this.this == "duckdb_tables"`).
- mypy flagged a variable (`cols`) reused with two different element types (`list[str]` for the
  aggregate-function check, then `set[str]` for the additive-count check) in the same function
  scope. Fixed by giving the second one its own name (`addend_cols`).
- mypy flagged `sqlglot.parse()`'s return type (`list[Expr | None]`) as incompatible with the
  helper functions' `exp.Expression` parameters, even after filtering out `None` entries earlier
  in the same function -- mypy doesn't narrow a list element's type from a filter applied to a
  different list. Fixed with an `assert ... is not None` plus `cast("exp.Expression", ...)` at
  the one point the value is actually used, rather than loosening every helper's signature.

**Metrics:** 82 tests pass (+23 for the validator: 59 -> 82). ruff and mypy clean.

## 2026-10-14 · Day 3, step 4 · Text-to-SQL: schema linking, retrieved examples, self-correction

**Covered:** `copilot.sql.service.TextToSqlService.answer(question, role)` -- one business
question in, either real rows or an explicit abstention out. Three new pieces feed it:

- **`copilot.sql.schema`** builds the prompt's schema card straight from
  `data/snapshot/MANIFEST.json` (the real column list) filtered through `disclosure.yaml`'s
  role rules -- a viewer is never even shown a table it can't read, so the model can't write
  SQL against it in the first place. `MeetsMinK` (our own bookkeeping column) is stripped.
- **`copilot.sql.examples`** retrieves the 3 most lexically similar question/SQL pairs from
  the 40-question golden set (Jaccard overlap on tokens, no embeddings -- 40 rows doesn't
  justify a vector index) to show as few-shot examples, restricted to a role no more
  privileged than the caller's so an example never teaches a viewer an analyst-only query shape.
- **`copilot.sql.service`** wires the schema card + examples + the data-coverage rules into
  `prompts/text_to_sql/v1.yaml`, asks for forced structured output (`sql`, `assumptions`,
  `abstain_reason`), and runs the result through `copilot.sql.validator.validate()` before
  ever executing it. A rejected query's exact violation codes are fed back as the next user
  turn (layer 4, "self-correction"); after `MAX_SELF_CORRECTIONS = 2` failed retries the
  service abstains with the last violation instead of ever running unsafe or wrong-shaped SQL.

Added a sixth layer to the validator while building this (layer 3, "data coverage" in the
spec): `_check_coverage()` catches an `=`/`IN`/`BETWEEN` filter on `SalesYear`/`SalesMonth`
that falls entirely outside what the data covers (2024, months 1-12) -- the exact "what was
revenue in Q1 2025" trap from the spec's trap table -- before it can silently return 0 rows.

**Verification, not just unit tests:** ran `validate()` against all 33 real SQL-bearing golden
questions (role and SQL exactly as recorded in `evals/datasets/golden_v1.jsonl`) -- **0 false
positives**: every already-correct, already-verified golden query still passes every layer.
Also ran `build_schema_card()`/`retrieve_examples()` against the real snapshot and golden set
(no LLM call) to confirm the wiring works outside the test fakes, not just inside them.

**Mistakes and fixes:**
- Same mypy pattern as `InsightService`: `LLMClient.structured()`'s generic return type
  (`tuple[T, CallMetrics]`) didn't narrow to `tuple[SqlGeneration, CallMetrics]` automatically.
  Same fix -- `cast()` at the one call site.
- `_check_coverage()`'s first draft only handled `=`. Extended to `IN` and `BETWEEN` once the
  "2025 and 2026" / range-filter cases were written as tests, so a model that wrote
  `SalesYear IN (2025, 2026)` or `BETWEEN 2025 AND 2026` wouldn't slip past an `=`-only check.

**Metrics:** 104 tests pass (+22 from step 5's 82: +6 coverage-layer validator tests, +5
schema, +7 examples, +4 service). ruff and mypy clean across the whole repo.

## 2026-10-14 · Day 3, step 6 · Golden v2 as a LangSmith dataset + evaluators

**Covered:** the 6 trap questions `docs/specs/text_to_sql_safety.md` specified for v2, added
on top of v1's frozen 40 (`evals/datasets/golden_v2.jsonl`, 46 total; `golden_v1.jsonl` never
touched). Every number in the 6 new questions was computed by actually running the matching
SQL against the real snapshot, not typed from the spec by hand -- all five exactly match the
spec's quoted figures: total freight $1,640,474.69, blended margin 28.72% (vs. 5.31% from the
wrong `AVG(BlendedMarginPct)`), 2,127 loss-making SKUs and 6,334 dead-stock SKUs reported
separately (never 8,461). `golden_v2.manifest.json` pins its SHA-256 the same way v1's does.

**`copilot.evals.evaluators`** -- two scores per question, kept separate on purpose:
- `execution_accuracy`: did the system behave right (answer vs. abstain) AND, when it
  answered, return the right numbers (result-set match, 0.01 numeric tolerance,
  order-insensitive unless the question is a `trend` category). Abstaining is a pass when the
  golden expects a refusal and a fail when it expects an answer, and vice versa -- behaviour
  and numbers are graded together because either one alone hides the other kind of failure.
- `leakage_free`: re-validates whatever SQL actually ran through the exact same
  `copilot.sql.validator.validate()` the service already called. This can never disagree with
  the validator about what's safe -- it exists to catch a future *service* bug (e.g. running
  SQL from a rejected attempt by mistake), not a validator bug, so a correct-looking row count
  doesn't quietly hide that the wrong query produced it.

**`copilot.evals.langsmith_sync`** -- `sync_golden_dataset()` makes the LangSmith dataset
`vendor-copilot-golden-v2` exactly mirror the JSONL file: clear-then-recreate rather than a
partial diff, since 46 rows makes that simpler to reason about than matching stale examples.
Tested against a hand-written fake client (same pattern as the Anthropic SDK fakes) -- no
network call, no API key. `scripts/push_golden_to_langsmith.py` is the real one-line CLI that
runs this against your actual `LANGSMITH_API_KEY` -- next for you to run on your machine.

**Mistakes and fixes:**
- `TextToSqlResult` didn't carry cost/latency, so an eval run had nowhere to report spend.
  Added `total_cost_usd` / `total_latency_s` / `llm_calls`, accumulated across every attempt in
  the self-correction loop (not just the last one) -- a question that took 2 retries should
  show as 3x the cost of one that didn't, not hide the retries' cost.
- mypy flagged `_values_match()`'s equality fallback (`got == want`) as returning `Any`
  instead of `bool` -- Python's `==` can return anything if a value overrides `__eq__`. Fixed
  with an explicit `bool(...)`.

**Metrics:** 136 tests pass (104 after step 4 -> 126 with +17 `evaluators` and +5
`langsmith_sync` tests -> 136 with +10 `test_golden_v2.py`). `verify()` against the real
snapshot: 0 mismatches across all 46 questions. ruff and mypy clean.

## 2026-10-14 · Day 3, step 8 · Effort lab (sweeps `effort`, not temperature)

**Covered:** `copilot.evals.effort_lab.run_effort_lab()` -- the rebuilt version of the
sprint plan's original "temperature lab", per ADR-005's correction from step 1 (this model
generation has no `temperature`/`top_p`/`top_k` parameter at all; `output_config.effort` is
the nearest per-call lever, and it trades reasoning depth for latency/cost, not output
diversity at fixed sampling). Runs the same golden questions at every one of the 5 effort
levels and scores each run with step 6's evaluators, so the comparison uses real behaviour
and real numbers, not a model's self-report.

Metrics per effort level, same ones the sprint doc specified for the temperature version:
execution accuracy, grounding (`leakage_free` here -- see step 6's entry for why it's kept
separate from accuracy), SQL diversity across repeats (only computed when `--repeats > 1`;
at 1 repeat there's nothing to compare a single run against, so it's reported as `n/a`
rather than a meaningless 0 or 1), average cost, average latency.

`scripts/run_effort_lab.py` is the real CLI -- makes actual Anthropic API calls, so it's for
you to run on your machine with your `ANTHROPIC_API_KEY`. Defaults to 3 representative
questions (a plain lookup, the ratio-of-sums margin question, and the Q1-2025 abstain trap)
x 5 effort levels x 1 repeat = 15 calls; `--repeats` and `--questions` are both overridable.

**Mistakes and fixes:**
- First draft of the SQL-diversity calculation mixed rows from different questions together
  before counting distinct SQL strings, which would have measured "are these two different
  questions' queries different" (trivially always yes) instead of "does the same question
  get a different query across repeats at this effort level." Fixed by grouping by
  `question_id` first, computing each question's own distinct-SQL fraction, then averaging
  across questions -- caught by writing
  `test_diversity_measures_fraction_of_distinct_sql_across_repeats` before trusting the logic.

**Metrics:** 140 tests pass (+4). ruff and mypy clean.

## 2026-10-14 · Day 3, step 9 (final item) · Tokenization lab

**Covered:** `copilot.evals.tokenization_lab.run_tokenization_lab()` -- compares three ways
of counting tokens on this project's own real prompts (the actual `text_to_sql` system prompt
rendered with a real schema card and real retrieved examples for two roles, plus one real
`vendor_insight` prompt): Anthropic's own token-counting endpoint
(`client.messages.count_tokens(...)`, a real authenticated call that returns an exact count
and is billed as a count request, not a completion), `tiktoken` (OpenAI's BPE encodings, a
local/offline approximation), and a Hugging Face `tokenizers.Tokenizer` (a different local/
offline approximation, different vocabulary again). The provider count is treated as ground
truth and the other two are scored against it (`pct_error_vs_provider`), rather than assuming
either approximation is close -- Anthropic has never published its own tokenizer, so there is
no way to know how close without measuring. Every method's average token count is also run
through the real Sonnet 5 pricing table (`copilot.llm.pricing.cost_usd`) to project a
cost-per-1,000-requests figure, so a wrong token count's dollar impact is visible, not just
its token-count impact.

`scripts/run_tokenization_lab.py` is the real CLI. Unlike every earlier "run this yourself"
script in this project, it needs more than just `ANTHROPIC_API_KEY`: `tiktoken` and the HF
tokenizer both need a one-time network download of their vocab files, and
`openaipublic.blob.core.windows.net` / `huggingface.co` were both outside this build
sandbox's proxy allowlist when this was written (confirmed by trying -- both calls came back
`403 Forbidden` through the sandbox's proxy, not assumed from the sandbox's general network
notes). Both are ordinary public downloads from a machine with normal internet access, so
this is expected to just work on yours.

**Mistakes and fixes:**
- First attempt tried to install and exercise a real Hugging Face tokenizer (`gpt2`, via the
  lightweight `tokenizers` package rather than the much heavier `transformers`) and real
  `tiktoken` directly in this sandbox to verify the adapters end-to-end. Both failed on the
  vocab download (proxy `403`). Rather than mocking around that silently, the module's own
  docstring and the script's own header now state the sandbox limitation explicitly, and the
  test suite uses a tiny WordLevel tokenizer built in-process with the real `tokenizers`
  library (exercises the real `.encode(text).ids` interface, no network) plus a whitespace
  stub standing in for tiktoken -- so what's tested is this module's logic, not a repeat of
  the already-confirmed fact that tiktoken/HF need a download.
- `tokenizers` (for the HF adapter) was not yet a project dependency; added via
  `uv add tokenizers` (pulls in `huggingface-hub`/`tqdm`/`hf-xet`, not the much larger
  `transformers`/`torch` stack, since only the pure tokenizer is needed here).

**Metrics:** 145 tests pass (+5 `test_tokenization_lab.py`). ruff and mypy clean across the
whole repo. This was the last item in Day 3's checklist (step 7, the question->SQL pair
generator, stays skipped per the sprint doc's own "likely cut" flag).

## 2026-10-14 · All four real-call scripts run on your machine; one real bug found and fixed

**Covered:** you ran all four "run this yourself" scripts for real, with your own keys:

- `scripts/push_golden_to_langsmith.py` -- created the `vendor-copilot-golden-v2` dataset,
  46 examples.
- `scripts/run_effort_lab.py` -- 15 real calls, $0.11408 total. `exec_acc` came back `0.67`
  at **every** effort level (low through max) -- identical across all 5, which is the
  signature of one specific question failing for a structural reason, not of randomness.
  The run also logged `llm.structured repair 1/1 after validation failure: model did not
  return a parseable SqlGeneration (stop_reason=max_tokens)` -- the exact same failure mode
  already fixed once for `vendor_insight` (13 Oct): the model's answer got cut off before it
  finished, because `max_tokens` was set too low.
- `scripts/run_tokenization_lab.py` (after the `.env`-reading fix below) -- real numbers:
  provider (ground truth) averaged 1889.2 tokens per prompt; `tiktoken` averaged 1092.2
  (**41.5% under** the real count); the HF `gpt2` tokenizer averaged 1252.8 (**32.6% under**).
  Projected to cost/1,000 requests at Sonnet 5 pricing: provider $5.28, tiktoken $3.68, HF
  $4.01 -- confirms the module's whole premise: both local approximations would make you
  *underestimate* your real bill by a third to over 40%, so neither is safe to budget from
  without checking it against the provider count first.

**Mistakes and fixes:**
- `scripts/run_tokenization_lab.py` built its Anthropic client with `anthropic.Anthropic()`
  (no arguments), which only reads a real OS environment variable, not a `.env` file. Every
  other script in this project goes through `copilot.settings.get_settings()` first (which
  does read `.env`), but this one script skipped that and talked to the SDK directly --
  worked right up until the first real API call, which failed with "Could not resolve
  authentication method." Fixed by routing it through `get_settings()` like everything else.
  Caught by the user actually running it on their machine, not by my own testing (I have no
  real key to run this script with).
- `prompts/text_to_sql/v1.yaml`'s `max_tokens` was `800`, too tight for what the model wants
  to write at higher effort levels before it finishes its structured answer -- same root
  cause and same fix pattern as the `vendor_insight` prompt's `700 -> 1200` fix (13 Oct):
  edited the existing v1 file in place (a capacity fix, not a behaviour change, so the "new
  version per behaviour change" rule doesn't apply), raised to `1500`.
- Added a per-question breakdown to `scripts/run_effort_lab.py`'s printed output (previously
  it only printed the average across questions per effort level, which hides a single
  question failing every time behind an unchanging-looking number) -- next real run will
  show exactly which question is wrong and whether the `max_tokens` fix resolved it.

**Metrics:** 145 tests pass still (no new tests this entry -- the changes are a prompt
constant and a print statement, both exercised by the real run above rather than new unit
tests). ruff and mypy clean.

## 2026-10-14 · Real bug found: execution_accuracy required an exact column-name match

**Covered:** you re-ran `scripts/run_effort_lab.py` after the `max_tokens` fix above (15
calls, $0.11907). The `max_tokens` fix worked -- no more truncation/repair warnings -- but
`gq-045` (the blended-margin trap question) still scored `exec_acc = 0.00` at every effort
level, while `gq-001` and `gq-042` scored `1.00` every time. The per-question breakdown
(added in the previous entry) made this visible: `gq-045`'s SQL was
`SELECT ROUND(100 * SUM(TotalGrossProfit) / SUM(TotalRevenue) ...` -- correct, the same ratio
the golden answer uses, just with its own column alias instead of the golden's
`blended_margin_pct`.

The real bug was in `_row_matches()` (`copilot.evals.evaluators`, written Day 3 step 6):
it required `set(got) == set(want)` -- the *column names* had to match exactly, not just the
values. The spec this evaluator is supposed to implement
(`docs/specs/text_to_sql_safety.md`: "result-set match against the golden `expected_rows`
(**values**, not just row count)") never says column names must match, and a correct SQL
query is free to alias a computed column however it likes. Confirmed locally (no API call
needed) before touching any code:
```python
>>> rows_match([{"blended_margin": 28.72}], [{"blended_margin_pct": 28.72}])
False   # same value, different alias -- should have been True
```

**Mistakes and fixes:**
- `_row_matches()` now compares **values in column order**, not by column-name set --
  `run_rows()` builds each row dict from the cursor's column order and Python dicts preserve
  insertion order, so `.values()` on both sides is exactly "the columns in SELECT order."
  Row-length mismatch (different number of columns) still correctly fails, since that's a
  real shape difference, not an aliasing difference. 3 new tests added, including one that
  reproduces the exact 14 Oct failure (`blended_margin` vs. `blended_margin_pct`, same value)
  and one guarding that a genuinely wrong value still fails regardless of its column name.
- This was a scoring-harness bug, not a text-to-SQL bug -- the effort lab's `exec_acc = 0.67`
  was an artifact of the eval code being wrong, not of the model answering wrong. Worth
  re-running `scripts/run_effort_lab.py` once more to get a real (fixed) accuracy number
  logged, though not urgent.

**Metrics:** 148 tests pass (+3). ruff and mypy clean across the whole repo.

## 2026-10-14 · Day 4 steps 1-3: knowledge corpus, chunking, embeddings + Chroma store

**Covered:**

- **Found and recovered uncommitted Day 4 step 1.** The working tree at the start of this chat
  already had a complete, tested knowledge corpus (`knowledge/{data_dictionary,
  metric_definitions,decision_log,methodology}.md` + 10 synthetic vendor contracts in
  `knowledge/contracts/`) and `copilot.rag.corpus` (frontmatter + body parser,
  `check_corpus_against_policy` drift check) with 10 passing tests -- built in an earlier
  session but never staged or pushed. `docs/PROJECT_PROGRESS.md` and `docs/HANDOFF.md` both
  said Day 4 was "Not started", which was wrong. Verified the files against the live
  `policies/disclosure.yaml` and the full check suite before trusting them, then committed as
  a correction (`5cbf949`) rather than silently redoing the work or leaving it stranded.
- **Step 2: heading-aware chunking** (`copilot.rag.chunking`). Splits at every Markdown heading
  (the real semantic boundaries in this hand-curated corpus -- see the module docstring for why
  fixed-size/semantic chunking were rejected), re-splitting by paragraph with overlap only when
  one section runs over ~1000 chars. `chunk_id` is stable across re-chunks of unchanged content;
  `content_hash` is a pure function of chunk text, used by step 3's idempotent upsert.
- **Step 3: local embeddings + Chroma store** (`copilot.rag.embeddings`, `copilot.rag.store`).
  `SentenceTransformerEmbedder` wraps the local `all-MiniLM-L6-v2` model (no API key, no
  per-call cost); `FakeEmbedder` is a deterministic no-network stand-in used by every test.
  `ChunkStore.upsert` is keyed by `content_hash`, not `chunk_id`, so a full rebuild skips every
  unchanged chunk. `scripts/build_rag_index.py` runs the real pipeline on your machine (needs
  no API key, just internet access to the Hugging Face Hub for the model download).
- Updated `docs/CODE_MAP.md` with the new RAG/Knowledge layer section, per its own standing
  rule, and moved `src/copilot/rag/` out of the "not yet started" list.

**Mistakes and fixes:**

- First version of `chunking._split_oversized` packed the heading line as if it were just
  another paragraph, so a single over-long section produced an orphaned chunk containing only
  its heading, plus a second chunk with the heading duplicated into the content. Caught by a
  test expecting one chunk for one oversized paragraph, got three. Fixed by splitting the
  heading line out of the content before packing and re-prefixing it onto every resulting piece.
- `SentenceTransformerEmbedder`'s dimension-mismatch guard originally checked the loaded model's
  dimension *after* loading it, which meant the only way to test the guard would have been a
  real network call to the Hugging Face Hub (blocked in this sandbox). Tested instead by
  monkeypatching a fake `sentence_transformers` module into `sys.modules`, so the guard logic is
  covered without ever reaching the network -- and a separate test confirms the real embedder
  never loads anything on construction, only on the first `embed()` call.
- `chromadb.EphemeralClient()`'s backing storage turned out to be process-wide, keyed by
  collection name, not isolated per client instance -- early versions of the store tests all
  wrote to a collection literally named `"test-collection"` and saw each other's chunks. Fixed
  by giving every test fixture a unique `uuid4`-suffixed collection name.
- Several `ruff` findings on the first pass of `store.py`: two bare `assert` statements doing
  type-narrowing in production code (`S101` -- asserts are for tests, not runtime type guards;
  replaced with `typing.cast`, since this module is trusted to only read back metadata it wrote
  itself) and three `zip()` calls without `strict=` (`B905`; added `strict=True` since every one
  of those pairs must be equal length or something is already wrong upstream).

**Metrics:** 184 tests pass (+36 over the Day 3 handoff's 148: +10 corpus, +9 chunking, +7
embeddings, +10 store). ruff and mypy (strict) clean across the whole repo. Snapshot rebuilt
fresh from the public analytics repo's workbook: 126-row vendor tables, 1,400-row vendor-month
demand, 399-row SKU health mix -- matches the canonical figures, no drift.

**Costs:** $0 -- nothing in Day 4 steps 1-3 calls a paid API; `SentenceTransformerEmbedder` is
local and free once its weights are downloaded.

**Open:** steps 4-7 of Day 4 (hybrid BM25+vector retrieval with RRF, the permission filter
inside the vector query, the Corrective RAG loop in LangGraph, and the recall@5/MRR/Ragas eval
on 20 labelled questions) still ahead. `scripts/build_rag_index.py` has not been run for real
yet -- needs your machine, per the pattern above.

## 2026-10-14 · Day 4 step 4: hybrid BM25 + vector retrieval, fused with RRF

Built `copilot.rag.retrieval`: `BM25Index` (pure-Python Okapi BM25 over chunk text, via the new
`rank-bm25` dependency, rebuilt in memory from the chunk list each time -- no incremental-update
story needed at hundreds-of-chunks scale) + `reciprocal_rank_fusion()` (the plain RRF formula,
`sum(1/(k+rank))` across however many rankings are passed in, default `k=60` -- the constant
Cormack, Clarke & Buettcher (2009) used and that most hybrid-search writeups since have kept) +
`HybridRetriever`, which runs a BM25 search and a `ChunkStore.query()` vector search over the
same chunk list and fuses the two rankings into one.

**Why fuse at all:** vector search catches paraphrase (different words, same meaning) but is
weak on exact identifiers -- a vendor code, a clause number, a dollar figure -- because those
tokens don't sit near each other in embedding space the way their meaning would suggest. BM25
is the reverse: strong on exact terms, blind to paraphrase. RRF fuses *ranks*, not raw scores,
specifically so BM25's unbounded term-frequency scores never need calibrating against Chroma's
cosine distances -- two completely different scales that RRF never has to compare directly.

**Cut from this step:** a cross-encoder reranker on the fused candidates. Real quality lever,
but a second model to load and run per query, and this step's job was to get the fusion
mechanics right first (BM25 index, RRF math, candidate-pool sizing) before adding a second
stage on top. `RetrievedChunk` already carries each chunk's full text, so a reranker slots in
later as a third stage without touching this module's contract. Logged as a cut, not an ADR --
same posture as the embedding model and vector store (a standard default, not a build-vs-buy
decision with real alternatives measured against it).

**No permission filtering here either** -- that's step 5, which wraps `HybridRetriever` rather
than changing it, same relationship step 4 has with `ChunkStore.query()`.

Tests (12, `tests/test_rag_retrieval.py`) check: BM25 ranks more term-overlap higher and drops
zero-overlap chunks entirely (a 0 score is "no match," not "weak match," so keeping it in the
ranking would let RRF give it undeserved credit); the RRF formula against hand-computed values
for a known input; that an item appearing in both rankings outranks one that's rank-1 in only
one (the actual property RRF buys you); and, at the `HybridRetriever` level, that a chunk with
*zero* lexical overlap with the query is still retrieved -- via the vector ranking alone --
something BM25-only retrieval would have missed outright. `FakeEmbedder` isn't semantically
aware (see its own docstring), so that last test controls the vector signal the only reliable
way available: making the query text exactly equal one chunk's text, which gives it the nearest
possible vector distance (0) regardless of lexical overlap with anything else in the corpus.

Updated `docs/CODE_MAP.md` with the new `retrieval.py` entry (same commit, per the standing
rule), corrected the `store.py` entry's now-stale forward reference to "no BM25 fusion yet,"
and moved the "not yet started" note from "steps 4-7" to "steps 5-7."

**Mistakes and fixes:**

- First cut of `BM25Index` tests used identical filler text across every chunk in a
  `n_results`-respecting test. BM25's idf term goes non-positive when a term appears in every
  document in the corpus, and the library floors that near zero -- which this module's own
  `score > 0` filter then (correctly) treated as "no real match" and dropped everything. Not a
  bug in `retrieval.py` itself, just a test corpus that accidentally hit BM25's documented edge
  case; fixed by giving each filler chunk distinct text.
- `rank-bm25` ships no type stubs or `py.typed` marker, so `mypy --strict` flagged the import.
  Added a scoped `[[tool.mypy.overrides]]` entry naming `rank_bm25` specifically (not a
  repo-wide `ignore_missing_imports`), since the surface actually used (`BM25Okapi`,
  `get_scores`) is tiny and stable.

**Metrics:** 196 tests pass (+12 over the 184 after Day 4 steps 1-3). ruff and mypy (strict)
clean across the whole repo.

**Costs:** $0 -- BM25 is pure in-memory lexical scoring, no API calls; every test uses
`FakeEmbedder` for the vector half.

**Open:** steps 5-7 of Day 4 (the permission filter inside the vector query, the Corrective RAG
loop in LangGraph, and the recall@5/MRR/Ragas eval on 20 labelled questions) still ahead.
`scripts/build_rag_index.py` still hasn't been run for real on your machine.

## 2026-10-14 · Day 4 step 5: permission filter inside the vector query

Built `copilot.rag.permissions.PermissionedRetriever` -- role-aware counterpart to
`HybridRetriever`, same RRF fusion mechanics, but every chunk either underlying ranking can
return is scoped first to what the requesting role may see.

**Why "inside the vector query," mechanically:** filtering ineligible chunks out of an
already-fixed-size result set silently returns fewer than `n_results` whenever permissions trim
the field -- "ask for 5, lose 3 to permissions, get back 2." Pushing the restriction into the
ANN search itself means every chunk that comes back was already eligible, so the result count
doesn't degrade with how restrictive the role is. Implemented by adding an optional `where`
parameter to `ChunkStore.query()` (default `None` -- every pre-step-5 caller and test is
unaffected) and having `PermissionedRetriever` pass `{"data_class": {"$in": [...]}}`, built from
the set of data classes the role may see. BM25 has no per-call filter to push into (`BM25Okapi`
scores a fixed in-memory corpus), so the same principle is enforced one layer up instead: the
role-scoped BM25 index is built from only the visible chunks in the first place, rather than
built from everything and filtered after scoring.

**Authority, deliberately not the chunk's own field:** `DisclosurePolicy.can_view(role,
data_class)`, re-derived from the live policy on every call -- not `chunk.allowed_roles`, even
though `copilot.rag.corpus.check_corpus_against_policy` already checks at ingest time that the
two agree. Same "the policy is the one source of truth" posture that check already takes toward
the whole corpus; a disclosure boundary shouldn't have two places that can each say yes.

Refactored `copilot.rag.retrieval` to pull the RRF-to-`RetrievedChunk` assembly logic (fuse the
two rankings, resolve IDs back to chunks, cap at `n_results`) out of `HybridRetriever.retrieve()`
into a standalone `fuse_rankings()` function, so `PermissionedRetriever` reuses the identical
assembly code rather than a second, parallel copy of it that could drift. `HybridRetriever`
itself is otherwise unchanged -- still unrestricted, still what step 4 built.

Updated `docs/CODE_MAP.md`: new `permissions.py` entry, corrected `store.py`'s and
`retrieval.py`'s now-stale text, and moved the "not yet started" note from "steps 5-7" to
"steps 6-7." Code Map artifact updated in the same sitting, per the standing rule.

Tests (12 new: 10 in `tests/test_rag_permissions.py`, 2 in `test_rag_store.py`): every role
(`anonymous`/`viewer`/`analyst`/`approver`/`admin`) sees exactly the data classes the live
policy grants it, over three identically-worded chunks of different classes so term overlap
can't explain the difference; a chunk tagged `restricted` is unretrievable by any role,
including `admin` (nobody may read `restricted`, per the policy itself); the "inside, not after"
claim is proven directly -- five confidential chunks plus one public chunk, `candidate_pool=1`,
role `anonymous`: a post-hoc filter would almost certainly retrieve a confidential chunk and
return nothing, the `where`-pushed-down version always finds the public one; and BM25's
role-scoped index test uses a term that appears in exactly one (ineligible) chunk to show that
chunk is absent entirely, not merely out-ranked.

**Mistakes and fixes:**

- `ChunkStore.query()`'s new `where` parameter failed `mypy --strict`: a plain
  `dict[str, object] | None` isn't assignable to Chroma's own `Where | None` type. Fixed with
  the same `cast()`-from-a-string-quoted-type pattern already used elsewhere in this file for
  `embeddings`/`query_embeddings`/`metadatas`, importing `chromadb.api.types.Where` under a
  `noqa: F401` (used only inside the quoted cast, same as `Sequence` above it).

**Metrics:** 208 tests pass (+12 over the 196 after Day 4 step 4). ruff and mypy (strict) clean
across the whole repo.

**Costs:** $0 -- no new dependency, no API calls; tests use `FakeEmbedder` and the real
`load_policy()` against `policies/disclosure.yaml` (no network, it's a local file).

**Open:** steps 6-7 of Day 4 (the Corrective RAG loop in LangGraph, and the recall@5/MRR/Ragas
eval on 20 labelled questions) still ahead. `scripts/build_rag_index.py` still hasn't been run
for real on your machine.

## 2026-10-14 · Day 4 step 6: Corrective RAG loop in LangGraph

Built `copilot.rag.corrective.CorrectiveRagService` -- a retrieve/grade/rewrite/generate/abstain
loop over the existing `PermissionedRetriever`, implemented as a LangGraph `StateGraph` rather
than hand-rolled control flow, since the loop has real branching (grade can route to generate,
rewrite, or abstain) that a graph makes easier to read and to extend later than a chain of `if`s.

**Why Corrective RAG (Yan et al., 2024), reduced:** the paper's loop is retrieve -> grade ->
[correct via query rewrite + web search | generate | abstain]. This repo's ADR-002 already rules
out fetching anything outside the licence-safe internal corpus, so the "incorrect -> external web
search" branch has no home here -- the rewrite-and-retry branch retries the *same* corpus with a
reformulated query instead, bounded by `MAX_CORRECTIONS = 2`, then falls through to abstain. This
is a simplification that follows directly from an already-made decision (ADR-002), not a new
build-vs-buy call, so it's logged here and in `PROJECT_PROGRESS.md` rather than as a new ADR.
Mirrors the existing `MAX_SELF_CORRECTIONS` retry-then-give-up shape in
`copilot.sql.service` -- same posture: bounded retries, then an honest "I don't know" over a
weakly-grounded answer.

Graph nodes: `retrieve` (calls the injected `Retriever` Protocol -- a stub in tests, the real
`PermissionedRetriever` in production, so tests never subclass the real retriever); `grade`
(structured LLM call, one relevance verdict per retrieved chunk, skipped entirely -- no LLM call
at all -- when retrieval returned nothing); `rewrite` (structured LLM call, given the question and
every query tried so far, proposes one new query); `generate` (structured LLM call, grounded only
in the chunks the grade step marked relevant, forced to cite chunk ids actually shown to it);
`abstain` (no LLM call -- a plain refusal result with a reason). Routing after `grade`: enough
relevant chunks -> `generate`; not enough and corrections remain -> `rewrite` -> `retrieve` again;
not enough and corrections exhausted -> `abstain`.

New prompts: `prompts/crag_grade/v1.yaml`, `prompts/crag_rewrite/v1.yaml`,
`prompts/crag_generate/v1.yaml` -- same versioned-YAML convention as every other prompt in this
repo, loaded via `copilot.llm.prompts.load_prompt()`.

New dependency: `langgraph` (`uv add langgraph`).

Updated `docs/CODE_MAP.md` with a new `corrective.py` entry per the standing rule.

Tests (6, `tests/test_rag_corrective.py`), all against `FakeMessagesResource` and a stub
`Retriever` -- no network, no API key: answers directly when the first grade is already
sufficient; rewrites once then succeeds on the better query; abstains after exhausting the retry
budget; abstains *without* calling the LLM to grade when nothing is ever retrieved (proving the
skip-grading optimization is real, by asserting the exact `llm_calls` count); never cites a chunk
id the model wasn't actually shown; ignores a grade for a chunk id outside the retrieved set.

**Mistakes and fixes:**

- mypy: `_build_graph()`'s return type (`CompiledStateGraph[...]`) isn't worth spelling out for a
  value immediately `cast` back to `_State` at its one call site -- typed it `-> Any` with a
  `# noqa: ANN401` explaining why, rather than fighting the generic.
- mypy: `llm.structured(...)`'s generic return didn't resolve from the `output_model=` kwarg at
  three call sites (grade, rewrite, generate) -- same shape `sql/service.py` and
  `insights/service.py` already hit; fixed identically, wrapping each call in
  `cast("tuple[SpecificModel, CallMetrics]", ...)`.
- ruff `S101`: had a bare `assert result is not None` guarding a can't-happen path in `answer()`.
  Replaced with an explicit `if result is None: raise RuntimeError(...)`, since a bare `assert` is
  stripped under `-O` and ruff flags it in production code either way.
- ruff `E501`: two long lines, both fixed by `ruff format` auto-wrapping.

**Metrics:** 214 tests pass (+6 over the 208 after Day 4 step 5). ruff and mypy (strict) clean
across the whole repo.

**Costs:** $0 -- new dependency (`langgraph`) is free and local; every test runs against
`FakeMessagesResource`, no real API calls made in this sitting.

**Open:** step 7 of Day 4 (recall@5/MRR/Ragas eval on 20 labelled questions) still ahead.
`CorrectiveRagService.answer()` has not yet been called for real against a real index or a real
API key.

## 2026-10-14 · Day 4 step 7: RAG eval harness -- recall@5, MRR, cut-down Ragas

Built the Day 4 eval harness: a 20-question labelled golden set, free retrieval metrics
(recall@k, MRR), and a cut-down Ragas pair (faithfulness, context_recall) as hand-written
LLM-judge functions, plus a CLI script to run all of it.

**Golden set (`evals/datasets/rag_golden_v1.jsonl`, `copilot.evals.rag_golden`):** 20 questions --
one per vendor contract (q01-q10, role `analyst`, `confidential`), four over
`metric_definitions` (q11-q14, role `viewer`, `public`), three over `decision_log` (q15-q17, role
`analyst`, `internal`), two over `methodology` (q18-q19, role `viewer`, `public`), one over
`data_dictionary` (q20, role `viewer`, `public`). Labelled by `doc_type`/`vendor` plus a verbatim
`must_contain` substring rather than a hardcoded `chunk_id`, so the dataset survives future
re-chunking; `relevant_chunk_ids()` resolves the label to the actual current chunk id(s) at eval
time. Verified empirically, not just asserted: wrote and ran a throwaway validation script against
the real chunked corpus before building any eval module around the dataset, confirming all 20
questions resolve to exactly 1 chunk each.

**Retrieval metrics (`copilot.evals.rag_metrics`):** `recall_at_k` and `reciprocal_rank` (MRR's
per-question term) are pure arithmetic over chunk-id lists -- no LLM, no fakes needed, run for
real in any environment including this one.

**Quality metrics, cut down (`copilot.evals.rag_quality`):** the sprint's own step asked for the
full Ragas suite (faithfulness, answer relevancy, context precision, context recall); this step's
own cut-first note in `docs/HANDOFF.md` allows reducing to faithfulness + context_recall. Built as
two small structured-output LLM-judge calls through the existing `LLMClient`
(`faithfulness`/`context_recall`, both returning `copilot.evals.evaluators.EvalScore`) rather than
adding the `ragas` package -- `ragas` would bring its own parallel LLM-wrapper and dependency
surface alongside the `LLMClient` wrapper this repo already standardizes on, for two judges that
are each a two-field structured call. Consistent with the hand-written-evaluator pattern Day 3
already set (`copilot.evals.evaluators`), not a new ADR-level decision.

New prompts: `prompts/rag_faithfulness/v1.yaml`, `prompts/rag_context_recall/v1.yaml`.

New CLI: `scripts/run_rag_eval.py` -- retrieval metrics (free) run by default against whatever
real index already exists at `data/chroma/`; `--quality` additionally runs
`CorrectiveRagService.answer()` plus both judges per question (costs money, off by default);
`--questions` restricts to a comma-separated subset of golden ids.

Updated `docs/CODE_MAP.md` with a combined entry for `rag_golden.py`/`rag_metrics.py`/
`rag_quality.py` and a `run_rag_eval.py` entry, and closed out the "not yet started" note -- all
7 of Day 4's steps are now built.

Tests (19 new: 5 in `tests/test_rag_golden.py`, 10 in `tests/test_rag_metrics.py`, 4 in
`tests/test_rag_quality.py`), all free/offline: golden-set loading and role/data-class
consistency; the "resolves to exactly 1 chunk against the real corpus" check as an actual test,
not just the one-off validation script; `relevant_chunk_ids()` respecting `doc_type`/`vendor`
filters and case-insensitivity; every recall@k/MRR edge case (full credit, zero credit, fractional
credit for multiple relevant ids, empty relevant set); both score branches (1.0 and 0.0) for each
judge, including that the judge's free-text reasoning (`unsupported_claims`,
`missing_information`) surfaces in the score's `comment`.

Ran recall@5/MRR for real (not just unit tests) end to end over the full 20-question golden set
against the real knowledge corpus with `FakeEmbedder`: mean recall@5 = 0.40, MRR = 0.258. Reporting
these honestly as noise-level, not real retrieval-quality numbers -- `FakeEmbedder` has no
semantic notion of similarity, same caveat this project has applied to every other
FakeEmbedder-based number so far (e.g. step 3's idempotency check). Real numbers need
`scripts/build_rag_index.py` run on your machine first.

**Mistakes and fixes:**

## 16 Oct -- Day 4 step 7 closed for real: recall@5/MRR with the real embedding model

Ran `scripts/run_rag_eval.py` on the laptop against the real Chroma index (built by
`scripts/build_rag_index.py`, `sentence-transformers/all-MiniLM-L6-v2`, not `FakeEmbedder`):
mean recall@5 = 0.800, MRR = 0.662 over the full 20-question golden set. This replaces the
`FakeEmbedder` noise-level numbers above as the real retrieval-quality baseline for Day 4 step 7
and closes the "real embedding-model numbers" gap `docs/PROJECT_PROGRESS.md` had flagged as
still open.

4 of 20 questions (q01, q04, q05, q10) scored 0 on both metrics -- the correct chunk never
appeared in the top 5 at all. Checked two of them against the real corpus rather than assuming
a retrieval bug: q01 (Diageo North America payment terms, `must_contain` "Net 45 days from
invoice date") and q04 (Moet Hennessy Usa freight terms, `must_contain` "Vendor-paid freight
(FOB destination)") both fail because their exact `must_contain` phrase is **not unique to that
vendor** -- `grep` across `knowledge/contracts/` shows "Net 45 days from invoice date" verbatim
in 5 vendor contracts (Diageo, Moet Hennessy, Pernod Ricard, Brown-Forman, Bacardi) and
"Vendor-paid freight (FOB destination)" in 3 (Moet Hennessy, Diageo, Bacardi). The golden-set
resolver (`relevant_chunk_ids()`) correctly picks the one chunk matching both `vendor` and the
phrase, but the retriever itself ranks purely by semantic/BM25 similarity with no vendor
boosting, so five near-identical boilerplate sentences across different vendor docs embed to
nearly the same vector and the ranking becomes a near-coin-flip which vendor's chunk surfaces.
q05 (Constellation rebate %) and q10 (Ultra Beverage rebate %) root-caused the same day: every
one of the 10 vendor contracts' "Rebate structure" section ends in the identical boilerplate
suffix "% of qualifying net purchases" (`grep` across all 10 confirms it), differing only in a
leading number (1.5, 1.75, 2.0, 2.25, 2.75, 3.0, 3.25, 3.5, 3.75). Sentence embeddings are not
trained to represent numeric magnitude precisely, so ten near-identical sentences that differ
only by a digit or two embed to nearly the same vector -- which vendor's rebate chunk actually
surfaces in the top 5 for a generic "what's vendor X's rebate rate" phrasing is close to a coin
flip. This is the exact same underlying phenomenon as q01/q04 (shared contract boilerplate
across vendors), just hitting the "Rebate structure" clause family instead of "Payment
terms"/"Freight terms". All 4 misses now trace to one root cause, not four separate ones:
standardized contract language makes same-clause-type chunks across different vendors
semantically near-duplicate, and semantic retrieval alone can't reliably tell them apart without
either metadata-filtered/vendor-boosted retrieval or a CRAG-style grading step that would catch
a wrong-vendor chunk even when it ranks well.

This is a genuine retrieval-quality finding, not a bug in the eval harness or the golden set:
shared contract boilerplate across vendors is exactly the kind of near-duplicate-text case that
motivates CRAG's grading step (Concept 04 of the explainer artifact) or a vendor-aware
re-ranking boost -- neither built yet. Logged here rather than silently patched.

- RAG golden-set labelling bug: q15's original `must_contain` phrase ("licence guard that rejects
  SKU-level columns") spanned a markdown soft-wrap line break in the source `decision_log.md`
  file, so the literal substring never appeared on one line in the stored chunk text --
  `relevant_chunk_ids()` resolved to 0 matches instead of 1. Caught by the validation script
  before any eval module was built around the dataset, not after. Fixed by rewriting q15's
  `must_contain` to a phrase confirmed to sit entirely on one source line ("aggregate-only Parquet
  snapshot built from the analytics project's Gold views"), then re-ran the validator to confirm
  all 20 questions resolve cleanly.
- mypy: same `llm.structured(...)` generic-resolution issue as step 6, at two call sites
  (faithfulness, context_recall) in `rag_quality.py` -- fixed identically with
  `cast("tuple[SpecificModel, CallMetrics]", ...)`.
- ruff `E501`: one long print-statement line in `run_rag_eval.py`, fixed by extracting
  `recall, rr = score.recall_at_k, score.reciprocal_rank` into local variables and shortening the
  f-string -- chosen deliberately over adding a `# noqa`, once I noticed the noqa option was also
  available.
- Left a stray `_Split = Literal["dog", "test"]` placeholder and an unused `Literal` import in
  `rag_golden.py` from an earlier draft; removed both and simplified `__all__` to the four real
  exports, self-caught before this was flagged.

**Metrics:** 233 tests pass (+19 over the 214 after Day 4 step 6). ruff and mypy (strict) clean
across the whole repo. All 20 golden questions verified to resolve to exactly 1 chunk each against
the real corpus.

**Costs:** $0 in this sitting -- retrieval metrics are pure arithmetic; quality-metric tests use
`FakeMessagesResource`; no real `CorrectiveRagService.answer()` or judge call has been made with a
real API key yet.

**Open:** Day 4 (RAG and advanced RAG) is now fully built, all 7 steps. Still open from earlier:
a third re-run of `scripts/run_effort_lab.py`, a real `TextToSqlService` call, Docker Desktop
install, AWS/domain/GitHub variables from Day 2 -- plus two new real-machine items from today:
`scripts/build_rag_index.py` for the real embedding index, and optionally
`scripts/run_rag_eval.py --quality` for real faithfulness/context_recall numbers. Next sprint day
is Day 5 (ML tools for the agents).

## 2026-10-14 · Day 5 steps 1 & 4: forecast tool + inventory tools

Built the Forecasting & Risk agent's demand forecast tool and the Inventory Planning agent's
safety stock / reorder point / EOQ tools -- the two Day 5 items that are fully computable now,
for real, against the already-built licence-safe snapshot (no API key, no network, no SKU-level
data needed; see the Day 5 plan note on why the risk classifier, steps 2-3, is different).

**Forecast tool (`copilot.ml.forecast`, `copilot.ml.metrics`):** `forecast_demand()` backtests
AutoETS against a plain one-step naive on `portfolio_monthly_demand`/`vendor_monthly_demand`,
using the analytics repo's own `forecast_backtest.py` methodology (rolling-origin, one-month-
ahead, expanding window) so the numbers are directly comparable. WAPE/MASE/bias
(`copilot.ml.metrics`) chosen over MAPE per the sprint doc and per that same script's own
documented reason (MAPE blows up near-zero actuals).

**Two real findings worth recording (not just "it runs"):**
1. `statsforecast`'s `AutoETS` raises `NotImplementedError("tiny datasets")` below 7 in-sample
   points (confirmed empirically) -- one more than the analytics repo's own `first_origin=6`.
   `ForecastRequest.first_backtest_origin` floors at 7 for this reason, documented in the
   field's own description so the constraint travels with the schema, not just a code comment.
2. Ran the real backtest against the real portfolio series: ETS and naive both score
   WAPE=0.1153, MASE=1.516, essentially identical point forecasts -- AutoETS's auto-selected
   trend component reduces to effectively no trend on this short, noisy 12-month series. This
   is a real result, not a bug (re-verified by hand, and it matches the existing honesty
   pattern from `forecast_backtest.py`: "Excel's gamma comes out at ~0, so the ETS projection
   reduces to a straight trend" -- same phenomenon, different ETS implementation). WAPE 11.5%
   also lines up with that script's own documented "portfolio naive 11.8%" baseline, which is a
   good independent sanity check that this reimplementation is measuring the same thing.

**Inventory tools (`copilot.ml.inventory`):** standard OR formulas (Silver/Pyke/Peterson for
safety stock/ROP; Wilson 1913 for EOQ). `demand_stats_from_backtest()` bridges a
`ForecastResult` to these formulas' (mean, std-dev) inputs.

**Mistake caught and fixed before it reached a test:** the first version of
`demand_stats_from_backtest()` computed demand std-dev from variance *across the forecast
points themselves*. Both models here can (and did, for the portfolio series above) produce an
effectively flat forecast, which has zero variance by construction -- that would have silently
returned a zero safety stock, understating real risk rather than being a safe conservative
default. Fixed to use historical month-over-month variability instead (always non-zero for real
demand), with a fallback for the edge case of exactly 2 history points (1 diff, no sample
variance of a single number). Caught by running the real end-to-end forecast -> inventory
pipeline by hand before writing it up here, not by a test (the original tests were written to
match the bug, then rewritten once the bug was found -- see commit diff, not worth restating
test-by-test here).

Real numbers, portfolio, 3-month horizon, 1-period lead time, 95% service level, $500/order,
$0.50/unit/year holding cost: mean demand/period 3,758,005; std dev (from history) 363,277;
safety stock 597,537; reorder point 4,355,542; EOQ 300,320.

**New dependencies:** `statsforecast`, `scikit-learn`, `shap`, `xgboost` added together (steps
2-3 need the latter three; adding all four now means one `uv sync` instead of two). `pandas`
pinned down from 3.0.6 to 2.3.3 by `statsforecast`'s own dependency constraint -- full 233-test
suite re-run immediately after and confirmed clean before writing any Day 5 code, so the pin is
known-safe, not just assumed.

**Mistakes and fixes (mechanical):**
- `store.connect()` opens a read-only DuckDB connection that locks configuration on the shared
  in-process handle to that file; calling it twice in the same test (once to look up a real
  vendor name, once inside `forecast_demand()`) raised `InvalidInputException` on the second
  call's `SET enable_external_access`. Not a new bug in `store.py` -- every existing caller
  only ever opens one connection per call site. Fixed by reusing one connection across both
  calls in the affected tests, and confirmed `connect()` -> `.close()` -> `connect()` again
  works fine (own-connection tests, which `forecast_demand()` always closes, were never at risk).
- mypy: `float ** 0.5` and `int(row["year"])` from `DataFrame.itertuples()` both inferred as
  `Any` -- fixed with explicit `float(...)` wraps and switching to `df.to_dict("records")`
  (dict access type-narrows better than a generated namedtuple here).
- mypy: `scipy.stats`, `statsforecast.*`, `xgboost.*` ship no inline types or stubs for the
  pinned versions -- added to `[[tool.mypy.overrides]]` with the same `ignore_missing_imports`
  reasoning already on record for `rank_bm25` (small, stable surface used; not worth a hand-
  rolled stub file or an extra `-stubs` package fighting this project's pinned numpy/pandas
  versions).

Updated `docs/CODE_MAP.md`: new "ML tools" section for `copilot.ml.metrics`/`forecast`/
`inventory`; "Not yet started" note narrowed (ml/ is no longer empty).

Tests (34 new: 12 in `tests/test_ml_metrics.py`, 10 in `tests/test_ml_forecast.py`, 12 in
`tests/test_ml_inventory.py`). `test_ml_forecast.py`'s 4 `forecast_demand()` end-to-end tests
skip when the snapshot isn't built, same pattern as `tests/test_store_security.py` -- but it was
built and all 4 ran for real in this sitting, not skipped.

**Metrics:** 267 tests pass (was 233). ruff and mypy (strict) clean across the whole repo
(58 source files, up from 55).

**Costs:** $0 -- every number in this entry came from code run in this session against the
already-built licence-safe snapshot; no LLM call, no API key, no network access beyond the one
already-cloned analytics repo and `uv sync`'s package downloads.

**Open:** steps 2-3 (risk classifier + XGBoost comparison) and step 6 (Model Selection Agent)
still ahead for Day 5.

## 2026-10-14 · Day 5 steps 2-3 & 5 · SKU risk classifier + CSV run-log

**Covered:** `copilot.ml.risk_classifier` -- Random Forest + XGBoost SKU risk classifier,
leakage-safe by construction, with calibration curve + SHAP top drivers; `copilot.ml.run_log` --
the CSV run-log (step 5; MLflow cut-first per sprint doc); `scripts/train_risk_classifier.py` for
the real `vw_PortfolioHealth` export, same never-in-chat convention as the other real-data
scripts.

**The leakage story, and the bug that initially hid it:** ADR-000 item 1 names `ProfitMargin` as
a leak -- the real view derives `HealthStatus` from a bucketed `ProfitMargin`, so a model that
sees `ProfitMargin` is reading the label-generating rule back off the number, not predicting
anything. `LEAKING_FEATURES` excludes it plus `MarkupPct`/`NetMarginAfterExcisePct` (same margin
family) for the "leakage-safe" feature set.

First two synthetic-data attempts produced **no accuracy/F1 difference at all** between the
leaky and safe fits -- the whole point of this module's docstring story wasn't showing up:
1. First fixture labelled `at_risk` via `(profit_margin < 0.08) | (stock_turnover < 0.5)`.
   `StockTurnover` (always in the "safe" set) alone was already near-perfectly predictive
   through its direct presence in the OR, completely overshadowing any margin-specific signal.
   Fixed by rebuilding the fixture around one shared latent "SKU health" factor `z`, with
   `ProfitMargin` carrying `z` plus its own idiosyncratic noise and the label thresholded
   *directly and only* on that noisy margin value (plus 3% label-flip noise) -- removing
   `StockTurnover` from the label rule entirely.
2. Leaky and safe fits were **still identical** after that rebuild. Root cause: `ActualPrice =
   PurchasePrice / (1 - ProfitMargin)` is an exact algebraic function of `ProfitMargin`, and
   `SalesToPurchaseRatio = TotalSalesDollars / TotalPurchaseDollars` reduces (once
   `TotalSalesQty ~= TotalPurchaseQty * StockTurnover` is substituted in) to
   `StockTurnover * (1 + MarkupPct)` -- a near-exact proxy for `ProfitMargin` that was sitting in
   `NUMERIC_FEATURES` but not in `LEAKING_FEATURES`, so it was present in *both* the leaky and
   "safe" feature sets and fully substituted for the excluded column. Fixed by adding
   `SalesToPurchaseRatio` to `LEAKING_FEATURES`. Confirmed by re-running the comparison: RF
   accuracy 0.834 -> 0.820, F1 0.291 -> 0.211; XGBoost accuracy 0.898 -> 0.886, F1 0.667 -> 0.596
   (leaky -> leakage-safe) -- a real, directionally-correct differential, and the safe model's
   SHAP drivers no longer include any margin proxy by name.

**Why this matters beyond this one fixture:** a feature excluded from a model's *literal* column
list can still leak the excluded signal back in through an algebraic combination of columns that
individually look unrelated to it. "Not in the leaky list" isn't sufficient; the feature actually
has to be checked for reconstructing the excluded one, which is why this got caught by running
the comparison and inspecting SHAP drivers rather than by code review alone.

**Also caught along the way:** SHAP's return shape for a binary `RandomForestClassifier`
differs by `shap`/`sklearn` version -- some combinations return a `list` of per-class arrays,
this pinned combination (`shap==0.53.0`, `sklearn==1.9.1`) returns one 3D
`(n_samples, n_features, n_classes)` array instead. Confirmed by direct inspection before fixing;
`train_and_evaluate()` now dispatches on both shapes so a future `shap` upgrade doesn't silently
break SHAP output.

**New dependency surface:** no new packages (scikit-learn/shap/xgboost were already added in
the steps-1-&-4 commit); added `[[tool.mypy.overrides]]` for `shap` and `sklearn.*`, which ship
no inline types for the pinned versions -- same `ignore_missing_imports` reasoning already on
record for `rank_bm25`/`scipy.stats`/`statsforecast`/`xgboost`.

**CSV run-log (step 5):** `copilot.ml.run_log.append_run_log()` appends one flat row per tool
call (`timestamp`, `tool`, `model`, JSON-encoded `params`/`metrics`) to a plain CSV, writing the
header on first use. One `log_*_run()` builder per ML tool. Deliberately not MLflow or a
database -- three tools called a handful of times a day don't need a tracking server; a CSV
`pandas.read_csv` or Excel opens directly is the honest-sized tool. `run_log.csv` is covered by
the existing blanket `*.csv` gitignore rule.

**Real-data script:** `scripts/train_risk_classifier.py` loads a CSV/XLSX export with the real
`vw_PortfolioHealth` column names, derives `is_at_risk` from `HealthStatus`, runs
`compare_models()`, prints the leaky-vs-safe differential and top SHAP drivers, and appends every
result to a run-log CSV. Smoke-tested in this sitting against a synthetic CSV (not the real
sheet, which never enters this session) to confirm the CLI, column-validation, and run-log wiring
all work end to end.

Updated `docs/CODE_MAP.md`: new entries for `copilot.ml.risk_classifier` and `copilot.ml.run_log`
in the "ML tools" section, and `scripts/train_risk_classifier.py` added to the "scripts you run
on your own machine" table.

Tests (18 new: 12 in `tests/test_ml_risk_classifier.py`, 6 in `tests/test_ml_run_log.py`).

**Metrics:** 285 tests pass (was 267). ruff and mypy (strict) clean across the whole repo
(61 source files, up from 58).

**Costs:** $0 -- synthetic fixture only, no LLM call, no API key, no network access beyond
`uv sync`'s package downloads (none needed this sitting -- no new dependencies).

**Open:** step 6 (Model Selection Agent, Addendum A1) is the only Day 5 item left.

## 2026-10-14 · Day 5 step 6 · Model Selection Agent (Addendum A1)

**Covered:** `copilot.agents.model_selection.ModelSelectionAgent` -- the LangGraph propose ->
critique -> revise -> abstain loop Addendum A1 calls for, plus its eval harness
(`copilot.evals.model_selection_golden`/`metrics`/`quality`, `scripts/run_model_selection_eval.py`).
This closes Day 5 entirely (all 6 steps).

**Design, following the Day 4 precedent directly:** the addendum explicitly names CRAG/Self-RAG-
style scrutiny as the mechanism, and `copilot.rag.corrective.CorrectiveRagService` is exactly
that shape already built here -- retrieve/grade/rewrite/generate/abstain. This agent reuses the
same shape with different nodes: propose a model choice (`copilot.llm` structured call against
a fixed, closed `MODEL_CATALOG` -- never an invented model family), critique it (a second
structured call that scrutinizes the proposal against the stated requirement and returns
`correct`/`incorrect`/`ambiguous` plus concerns and an optional suggested alternative), and
either accept, revise (fold the critique's feedback into the next proposal) and retry up to
`MAX_REVISIONS = 2`, or abstain -- same retry-budget-then-abstain posture as
`copilot.sql.service.MAX_SELF_CORRECTIONS` and `CorrectiveRagService.MAX_CORRECTIONS`.

**One deliberate simplification versus `CorrectiveRagService`:** that loop's "rewrite" node
needs its own LLM call because reformulating a search query is a creative task. Here, "revise"
only has to forward the critique's already-structured `concerns`/`suggested_model_family`
fields into the next proposal's feedback block -- plain string formatting of output the
critique call already produced, so `_revise` is pure bookkeeping with no LLM call of its own.
Logged here rather than as a new ADR, for the same reason Day 4's reranker/embedding-model
choices weren't: the overall shape, the retry-then-abstain posture, and the eval-split
philosophy below all follow directly from decisions this repo already made, not a new
build-vs-buy call -- so **no new ADR for Day 5** (handoff's placeholder ADR-006 wasn't needed).

**Model catalog is fixed and closed:** `random_forest`/`xgboost` (classification) and
`ets`/`naive` (forecasting) are backed by real tools already built this week
(`copilot.ml.risk_classifier`, `copilot.ml.forecast`); `kmeans` (clustering),
`logistic_regression`/`linear_regression` (classification/regression) are catalog entries only
-- K-Means already exists in the analytics repo per ADR-000 item 1, and logistic/linear
regression are the sprint doc's own worked examples -- so those three are correct *category*
picks today, with the actual tool implementation still ahead, not a gap in this agent.

**Eval harness, same free/judged split as the RAG harness (Day 4 step 7):** whether
`task_type`/`model_family` are correct is pure catalog-membership logic, so
`copilot.evals.model_selection_metrics.task_type_correct`/`model_family_acceptable` need no
LLM. What a free check can't see is whether the agent's final *reasoning* is actually grounded
in the requirement's own stated characteristics versus generic ML boilerplate that would read
the same for any requirement sharing its task type -- that's the one LLM-judge call
(`model_selection_quality.reasoning_grounded`), closing Addendum A1's "evaluated with LLM
evals" requirement. The golden set (`evals/datasets/model_selection_golden_v1.jsonl`, 8
requirements, 2 per task type) scores each question's `model_family` against an *accepted set*,
not one exemplar -- the catalog genuinely offers more than one reasonable pick for
classification (`random_forest`/`xgboost`/`logistic_regression`) and forecasting
(`ets`/`naive`), and penalizing a correct-but-different choice would be testing the dataset's
own arbitrary pick, not the agent.

**Not run for real this sitting:** unlike the forecast/inventory tools (real snapshot data, no
API key needed) and the risk classifier (synthetic fixture, no API key needed), this agent
needs a real `ANTHROPIC_API_KEY` for every single run -- there's no free half, since producing
even one `ModelSelectionResult` means running the propose/critique LLM loop. No key is loaded
in this session's `.env` (confirmed: `LLMClient()` raises `LLMCallError` as designed). Same
"run on your machine" posture as the effort/tokenization labs: `scripts/run_model_selection_eval.py`
is ready to run with your own key for the real per-question task_type/model_family/
reasoning_grounded numbers.

**Mistakes and fixes (mechanical):**
- First draft stashed the critique result under an undeclared TypedDict key
  (`state["_last_critique"]`) read back via `.get()` -- ruff/mypy didn't catch it immediately
  but it's fragile (a plain dict key, not part of `_State`'s declared shape) and left a dead
  `_revise_feedback` stub as a "documentation anchor" that was never called. Rewritten before
  committing: `last_critique: ModelCritique | None` is a proper declared field on `_State`, and
  a real `_revise` graph node (mirroring `CorrectiveRagService`'s `_rewrite`) does the feedback
  bookkeeping and increments `attempt`, with the dead stub removed entirely.
- ruff `S101` (no bare `assert` outside `tests/`) flagged 5 `assert proposal is not None`-style
  narrowings copied from `CorrectiveRagService`'s raise-not-assert posture inconsistently --
  fixed by converting every one to an explicit `if x is None: raise RuntimeError(...)`, same
  pattern `ModelSelectionAgent.select()`'s own "can't happen" guard already used.

Tests (14 new: 5 in `tests/test_model_selection_agent.py` -- accept-first-try, revise-then-
accept, abstain-after-exhausting-the-budget, an `ambiguous` verdict also triggering a revision
not acceptance, and the catalog-coverage check; 9 in `tests/test_model_selection_eval.py` --
golden-set shape, golden-set-vs-catalog drift guard, both free metrics' pass/fail/abstain cases,
both `reasoning_grounded` judge cases). All against `FakeMessagesResource`, no network, no API
key, same convention as `tests/test_rag_corrective.py`.

Updated `docs/CODE_MAP.md`: new "Model Selection Agent" section; `src/copilot/agents/` moved
out of "Not yet started."

**Metrics:** 299 tests pass (was 285). ruff and mypy (strict) clean across the whole repo
(66 source files, up from 61).

**Costs:** $0 -- no real LLM call made this sitting (no key available); every test runs against
the fake Anthropic SDK.

**Day 5 is now complete: all 6 steps shipped.** Open for Day 6: the multi-agent system in
LangGraph that actually calls these tools (forecast, inventory, risk classifier, model
selection) as agent tools rather than standalone functions.

## 2026-10-15 · Day 6: multi-agent system in LangGraph -- all 7 steps

**Steps 1-2 (contracts, specialists):** `copilot.agents.contracts.TaskSpec`/`AgentResult` are
the typed envelope master prompt C3 requires so no specialist passes free text to another.
The five specialists (`copilot.agents.specialists`) are thin wrappers around already-tested
Days 3-5 services/tools -- `run_data_analyst` -> `TextToSqlService`, `run_forecasting_risk` ->
`forecast_demand` (+ an optional synthetic-fixture risk classifier run, licence-safely, since
this repo's snapshot has no real SKU-level data), `run_inventory_planning` -> `compute_
inventory_plan`, `run_knowledge` -> `CorrectiveRagService`, `run_action` -> a new `action_draft`
prompt (drafts only, never sends -- Day 7's Guardian/approver flow owns that). Two small new
lookups were needed to fill `AgentResult.data_classes` honestly, the thing Day 7's Guardian will
read: `_sql_data_classes()` (parses generated SQL with sqlglot, looks up each table via the live
`DisclosurePolicy`) and `PermissionedRetriever.chunk_by_id()` (same idea for a cited chunk).

**Step 3 (Orchestrator):** `copilot.agents.orchestrator.Orchestrator` is this project's first
*parallel* LangGraph graph -- every earlier graph (`CorrectiveRagService`, `ModelSelectionAgent`)
was purely sequential/conditional. `_fan_out` is a routing function, not a node: it returns one
`Send` per planned task so independent specialists run as separate parallel invocations
(LangGraph's own mechanism for exactly this), with `results: Annotated[list[AgentResult],
operator.add]` as the join. **Real bug found and fixed before committing:** an empty plan (the
question needed no specialist) left `run_specialist` never invoked, and since the static
`run_specialist -> draft` edge is only traversed when `run_specialist` actually runs, `draft`
(and the rest of the graph) never ran either -- `RuntimeError: orchestrator graph reached END
without producing a result`. Fixed by having `_fan_out` return `[Send("draft", state)]` for an
empty plan instead of an empty list, and adding `"draft"` as a valid destination on the
`plan -> fan_out` conditional edge. Conflict handling is logged only (`conflicts_noted`), never
resolved or re-queried, per the sprint doc's own Day 6 cut-first list.

**Step 4 (Verifier):** reuses `ModelSelectionAgent`'s propose/critique/revise/accept shape
exactly, via a new `orchestrator_verify` prompt. `_verify` is the critique (one more structured
call scoring `grounded`/`citations_ok`/`sufficient`/`contradictions`); `_route_after_verify` is
pure routing (no LLM call); `_revise_draft` is pure bookkeeping that folds the verdict's
feedback into a new `feedback_block` on `orchestrator_draft`'s prompt for the next `_draft` call.
A draft that still fails after `MAX_VERIFICATION_LOOPS` (2) redrafts is finalized anyway with
`verified=False` rather than looping forever.

**Step 5 (budgets, enforced):** `AgentBudget.exceeds()` was defined in step 1 but nothing called
it -- `_run_specialist` now actually does, after waiting on each specialist through a
`ThreadPoolExecutor` bounded by `max_latency_s` (a specialist that doesn't return in time
becomes `status="failed"` with a "timed out" gap; the Orchestrator can only stop *waiting*, not
force arbitrary sync code to stop, same honest limitation every `concurrent.futures`-timeout
approach has). An `ok` result that overran its cost/llm_calls/latency budget is downgraded to
`status="partial"` with the specific overage named in `gaps`. `AgentBudget.effort` substitutes
for the sprint doc's original "temperature" ask, per the already-established finding (Day 3,
`copilot.llm.client`'s module docstring) that this Anthropic SDK/model generation has no
`temperature` parameter at all.

**Step 6 (checkpointer + LangSmith tags, Studio cut):** added `langgraph-checkpoint-sqlite` as
a dependency; `Orchestrator(checkpoint_path=...)` compiles with a local `SqliteSaver`, and
`answer(..., thread_id=...)` is the checkpoint key a run can be inspected by afterwards --
the thing LangGraph Studio would otherwise visualize, which is this step's one cut-first item
(an external tool to point at this process, not code to build). `_ls_extra()` renames/tags each
of `plan`/`draft`/`verify`'s own LLM call via `traceable`'s `langsmith_extra` call-time override
(no change needed to `LLMClient`), and `run_action` tags its own call the same way; the other
four specialists delegate to Day 3-5 services whose internal LLM calls aren't yet agent-tagged
-- noted as out of scope rather than silently left undone.

**Step 7 (10 multi-hop golden questions, harness):** `copilot.agents.wiring.build_executors()`
turns the five `run_*` functions into the `dict[AgentName, SpecialistExecutor]` map the
Orchestrator takes, against real services built the same way `scripts/run_effort_lab.py`/
`run_rag_eval.py` already build them. `copilot.evals.orchestrator_golden` defines 10 questions
(`evals/datasets/orchestrator_golden_v1.jsonl`) that each need 2+ specialists chained together
-- distinct from `golden.py`'s own "multi_hop" category, which is multi-step *SQL* answered by
one specialist alone. Each question is graded structurally (did the plan cover every specialist
it needed), not against a fixed reference answer, since grading multi-agent answer *content* is
this step's stretch goal, not its floor. `scripts/run_orchestrator_golden.py` is ready to run all
10 end to end on your machine with your own `ANTHROPIC_API_KEY` -- not run for real this sitting.

**Mistakes and fixes (mechanical), beyond the empty-plan bug above:**
- `tests/test_agent_specialists.py` initially imported `demand_stats_from_backtest` from
  `copilot.ml.forecast`; it actually lives in `copilot.ml.inventory` -- fixed the import.
- A real-snapshot test used `"DIAGEO"` as a vendor name; that vendor doesn't exist verbatim in
  `vendor_monthly_demand` (only `"DIAGEO CHATEAU ESTATE WINES"` and `"DIAGEO NORTH AMERICA
  INC"` do) -- fixed to use the real name, confirmed via a direct DuckDB query first.
- `run_action`'s first draft omitted `draft_type` from `prompt.render_user(...)`'s kwargs even
  though the prompt's `user_template` references `{draft_type}` -- `KeyError` at test time,
  fixed by adding the kwarg.
- Several ruff `E501`/`F401` across the new files, fixed by wrapping long lines/dict literals
  and removing unused imports -- same mechanical cleanup every day in this project needs.
- `mypy` flagged `langsmith_extra={...}` as a plain `dict[str, Any]` against `traceable`'s
  `LangSmithExtra` TypedDict parameter -- fixed by building it through `cast("LangSmithExtra",
  {...})` in both `orchestrator.py` and `specialists.py`.

Tests (46 new across six files): 10 `tests/test_agent_contracts.py`, 14 `tests/
test_agent_specialists.py`, 12 `tests/test_orchestrator.py` (step 3's original plan/fan-out/
join/draft/conflict suite, +2 verifier-loop tests from step 4, +4 budget/checkpoint-enforcement
tests from steps 5-6, +1 sqlite-checkpointer-persists test from step 6), 3 `tests/
test_orchestrator_wiring.py`, 5 `tests/test_orchestrator_golden.py`. All offline against
`FakeMessagesResource`, no network, no real API key, except the snapshot-gated real-data tests
(skipped gracefully when `data/snapshot/MANIFEST.json` doesn't exist, same `pytestmark_snapshot`
convention `test_ml_forecast.py` already set).

Updated `docs/CODE_MAP.md`: new entries for `copilot.agents.contracts`/`specialists`/
`orchestrator`/`wiring`, `copilot.evals.orchestrator_golden`, the three new `prompts/
orchestrator_*` YAMLs, and `scripts/run_orchestrator_golden.py` -- one `CODE_MAP.md` edit per
commit, per this project's standing rule (not batched at the end of the day).

**Metrics:** 345 tests pass (was 299). ruff and mypy (strict) clean across the whole repo
(72 source files, up from 66).

**Costs:** $0 -- no real LLM call made this sitting (no key available); every test runs against
the fake Anthropic SDK or a skipped-gracefully real-snapshot path.

**Day 6 is now complete: all 7 steps shipped** (LangGraph Studio itself cut-first, an external
tool rather than code). Open for Day 7: the Guardian (cross-model-family provenance/safety
check on `AgentResult.data_classes` vs. the requesting role and answer audience), the
interrupt -> approver flow `run_action`'s own `gaps` already points at, and guardrails/approvals
more broadly.

## 2026-10-15 · Day 7 · Guardian, guardrails and approvals

**Covered:** all 8 steps of the sprint doc's D7 (injection classifier cut-first, per the doc's
own cut-first line). Guardian node with 8 deterministic checks and ALLOW/REDACT/BLOCK/ESCALATE
outcomes; PII (Presidio + regex fallback), secret patterns, canary tokens in every agent's
system prompt; audit log; a graph topology test proving no path to `END` skips the Guardian;
an Action-draft approval gate (`interrupt()` -> Guardian -> approver approve/edit/reject); an
input gate (kill switch, length, injection heuristics, scope, rate limit, daily spend cap);
LangSmith trace masking; a 23-case privacy-leakage suite in CI (15 + 8 SQL red-team).

**Step 1-3 (Guardian, PII/canary/secrets, outcomes + audit log):** `Guardian.review()` runs
8 checks cheapest-first against a `_Reviewable` Protocol (not an import of `OrchestratorResult`
-- avoids a circular import with `orchestrator.py`, which has to import `guardian.py`): canary
leak, restricted-table-name leak, raw-row-shape (`RAW_ROW_PATTERN`: 10+ consecutive delimited
lines), role policy, vendor-facing-audience (an Action draft + any other specialist's non-public
data in the same answer), secrets, PII, and grounding (`not verified` -> ESCALATE, not BLOCK).
Worst-severity finding wins; every finding's code lands in `reason_codes` regardless of which
one decided the outcome. `copilot.guardrails.pii.find_pii` tries Presidio first (its
`AnalyzerEngine` built and cached once per process -- an uncached first attempt made the test
suite hang, reloading the spaCy model on every single call) and falls back to a deterministic
regex layer when Presidio/its model aren't usable; the regex layer is what every test and CI
run actually exercises. `copilot.guardrails.canary` appends one `CANARY-<AGENT>` marker per
call site to every system prompt this project builds. `copilot.guardrails.audit_log.
log_decision`/`log_approval` append JSON lines to a local, gitignored
`data/audit/guardian_log.jsonl`, independent of LangSmith on purpose.

**Step 4 (topology test):** `finalize` no longer edges straight to `END` -- it edges to
`guardian`, which (after step 5) shares the one path to `END` with `approval_gate`, itself only
reachable from `guardian`. The test asserts this against the *compiled* graph's own
`get_graph()` edges, not `_build_graph`'s Python source.

**Step 5 (approval gate):** confirmed the `interrupt()`/`Command(resume=...)` pattern against a
real `SqliteSaver` with a throwaway smoke script *before* writing the real wiring -- resuming
without a checkpointer raises `RuntimeError` from LangGraph itself, so an `Orchestrator` built
with no `checkpoint_path` skips the approval gate entirely rather than pausing on a run nothing
can resume. `resume_approval()` checks `approver_role in {"approver", "admin"}` in Python before
touching the graph at all. An `"edit"` decision is re-run through `self._guardian.review()`
before its text is accepted.

**Step 6 (input gate):** `InputGate.review()` runs kill switch, length, injection heuristics,
scope, rate limit, and daily spend cap, cheapest-first, BLOCK-only (nothing on the input side is
worth partially salvaging). `InputGate.record_spend()` is called by `Orchestrator.answer()`
after a run finishes with its real `total_cost_usd` -- the gate itself, running before this
request's own cost exists, can only ever check *past* spend.

**Step 7 (trace masking):** `LLMClient.complete`/`.structured` are decorated with
`process_inputs=mask_run_payload, process_outputs=mask_run_payload`
(`copilot.guardrails.trace_masking`) rather than threading a `langsmith.Client(anonymizer=...)`
through every call site. Two things ruled the `Client` approach out, both confirmed with
throwaway scripts first: constructing a `Client()` eagerly calls `GET /info` over the network;
and a masked client set as langsmith's own default via its `contextvars`-based context doesn't
survive crossing into `_run_specialist`'s `ThreadPoolExecutor` worker thread (`ContextVar.set()`
in the main thread is invisible to a plain new thread -- verified directly). `mask_run_payload`
hides the whole payload if a Restricted table/view name appears anywhere in it, otherwise
redacts PII/secrets recursively through every string value.

**Step 8 (23-case suite):** `tests/test_privacy_leakage_suite.py` names every case from the
master prompt's privacy-leakage categories (role escalation, poisoned contract, cross-vendor
draft, prompt extraction, raw rows, other vendors' terms, system prompts, API keys, other
users' memory, small-group figures) plus the 8 SQL red-team rows from `docs/specs/
text_to_sql_safety.md`, asserting the real mechanism that catches each one. Writing it surfaced
a real, previously-unguarded gap: nothing blocked an unbounded cross join (the existing
`LIMIT 200` cap bounds the output, not the join computation). Fixed with a new validator check,
`_check_cost_limit` (`sql_cost_limit`): blocks a join with no `ON`/`USING` *unless* `WHERE`
references columns from at least two of the joined tables by their table-qualified name --
verified against the real golden set first (`gq-025`'s genuine bounded-by-`WHERE` self-join
correctly still passes) before trusting the fix.

**Mistakes and fixes:**
- A circular import: `copilot.llm.client` needs `mask_run_payload` (step 7), which needs
  `SECRET_PATTERNS`; importing that from `guardian.py` closed a real loop (`guardian.py` imports
  `copilot.agents.contracts` for `AgentResult`'s type hint, which imports `copilot.llm.client`
  for `Effort`) -- confirmed by actually hitting the `ImportError` before fixing it. Fixed by
  splitting `SECRET_PATTERNS` into its own leaf module, `copilot.guardrails.secret_patterns`,
  with no project imports, used by both `guardian.py` and `trace_masking.py`.
- The real repo's `data/spend/daily_spend.json` got polluted to $10.02 for role `analyst` by
  the test suite itself (every orchestrator test building a plain `Orchestrator(...)` shares one
  default `InputGate()`, whose `SpendTracker` persists to that real file) -- this then broke 8
  unrelated orchestrator tests with a spurious `daily_spend_cap_exceeded` block, and one of the
  approval-resume tests on top of that (resuming a thread that was blocked before the graph ever
  ran, so there was nothing to resume). Fixed two ways: cleaned the polluted file, and added
  `tests/conftest.py`'s autouse `_isolated_spend_log` fixture so every test gets its own
  throwaway spend file (required changing `SpendTracker.__init__`'s default-path handling from
  a bound default-argument value to a body-level lookup, so `monkeypatch.setattr` on the module
  constant actually takes effect).
- `_check_cost_limit`'s first version used `statement.args.get("from")` -- this sqlglot version
  stores it under `"from_"` (`from` is a Python keyword), so the lookup silently returned `None`
  and the real golden query `gq-025` got false-blocked. Found by debugging the exact AST args
  keys directly rather than guessing, fixed the key name, reverified both the false-block case
  and the real-leak case.
- Test draft text containing day names ("by Friday", "by Monday") tripped Presidio's own
  `DATE_TIME` entity detection, REDACTing text the approval-gate tests expected to pass through
  unchanged -- fixed by rewording the fixture text, not by weakening the PII check.

**Tests (95 new):** 17 `tests/test_guardian.py`, 4 `tests/test_guardrails_pii.py`, 4 `tests/
test_guardrails_canary.py`, 4 `tests/test_guardrails_audit_log.py`, 2 end-to-end Guardian-wiring
tests in `tests/test_orchestrator.py` (step 4) + 8 approval-gate tests (step 5) + 3 input-gate
wiring tests (step 6), 18 `tests/test_input_gate.py`, 8 `tests/test_trace_masking.py`, 4 new
`sql_cost_limit` cases in `tests/test_sql_validator.py`, 23 `tests/test_privacy_leakage_suite.py`.
All deterministic -- no LLM call, no API key, same posture every other guardrail test in this
project takes.

Updated `docs/CODE_MAP.md`: new entries for `copilot.guardrails.guardian`/`pii`/`canary`/
`audit_log`/`input_gate`/`trace_masking`/`secret_patterns`, the `sql_cost_limit` addition to
`copilot.sql.validator`, the input-gate knobs added to `copilot.settings`, and `tests/
conftest.py` -- one `CODE_MAP.md` edit per commit, per the standing rule.

**Metrics:** 440 tests pass (was 345). ruff and mypy (strict) clean across the whole repo
(79 source files, up from 72).

**Costs:** $0 -- every Guardian/input-gate/trace-masking/privacy-suite test is deterministic;
Presidio's `AnalyzerEngine` and its `en_core_web_lg` spaCy model installed and ran without issue
this sitting (no API key needed for either).

**Day 7 is now complete: all 8 steps shipped** (the injection classifier cut-first, per the
sprint doc's own line). **ADR-006 (Guardian design) is still open** -- the required Day 7 ADR
per Addendum A1, waiting on the user's own answers to the template/questions rather than mine.
Open for Day 8: FastAPI `/ask` with SSE streaming, the UI, invite-code + API-key auth, Postgres
for checkpoints, the CI eval gate, latency budget work, and release `v0.1.0`.

## 15 Oct -- Handoff cross-check (chat 7), gap found and closed

Re-attached the repo, rebuilt the snapshot from the analytics repo's workbook, and reran every
check: 440/440 tests pass, ruff clean, mypy (strict) clean -- matches the Day 7 commit's own
claim exactly, nothing to correct there.

**Real gap found:** `docs/TRADEOFF_LOG.md`, mandatory per Addendum A1 section 2.2 from "the
current sprint day onward," did not exist through Days 1-7. Created it now, backfilled only
with before/after facts that already exist in this file (the `execution_accuracy` scoring fix,
the `sql_cost_limit` validator addition, the `unverified_grounding` -> ESCALATE routing choice)
-- no invented numbers, several cells marked "not measured" per the addendum's own rule. A full
golden-set execution-accuracy rerun after the `sql_cost_limit`/`execution_accuracy` fixes is
still owed and is carried forward as open measurement debt in that file.

**Still open, unchanged from the Day 7 commit:** ADR-006 (Guardian design) needs the user's own
written answers to the 4 questions (severity ordering, ESCALATE-with-no-reviewer-yet behaviour,
vendor-audience check scope, raw-row-shape detection approach) before the ADR document itself
can be written -- Addendum A1's process is the user writes the answers, not Claude. Presented
again this session since no prior file actually contains the template text itself (the Day 7
commit message said it was "presented to the user" but it lived only in that chat's turns, not
in a committed file).

## 22 Oct — Day 8 start: pre-existing production-blocking DuckDB bug found and fixed

Before any Day 8 code: fresh clone, `uv sync --frozen`, full suite run as a baseline. 25 failed,
415 passed — not the 440/440 the Day 7 commit and the 15 Oct cross-check both recorded.

**Investigated, not assumed.** 10 of the 25 (`test_store_security.py`'s whole parametrized
`test_engine_refuses` set, plus `test_aggregate_reads_still_work`) were all the same error:
`InvalidInputException: Cannot change configuration option "enable_external_access" - the
configuration has been locked`, thrown from `store.connect()`'s own `SET enable_external_access
= false`. Reproduced directly (not guessed): `connect()` called 3 times in one Python process
against the same snapshot path — call 1 and 2 succeed, call 3 raises. Root cause: DuckDB shares
one underlying database instance across every connection opened to the same file path within a
process; `SET lock_configuration = true` locks that shared instance, not just the connection
that issued it, so a later `connect()` reusing the cached instance hits an already-locked
config on its own `SET enable_external_access = false` — even though it's only re-asserting the
value already in force. This is a **real production blocker**, not a test-only artifact: the
planned `/ask` endpoint calls `store.connect()` once per request, so the second request into a
running server would have thrown this on every data-backed question.

**Fix:** pass `enable_external_access` and `lock_configuration` via `config=` at
`duckdb.connect()`-time instead of two `SET` statements after opening. Verified by direct repro
(4 repeated connects all succeed) and re-confirmed the security guarantee still holds (`SET
enable_external_access = true` against the 4th connection still correctly raises). Full suite
after the fix: 425 passed, 15 failed — all 15 are `CatalogException: Table ... does not exist`,
because this cloud session has no local `Vendor_Summary.xlsx` to run `scripts/build_snapshot.py`
against (licence rule: the workbook is local-only, never committed, and I'm not sourcing or
reconstructing it another way) — `data/snapshot/*.parquet` is correctly absent, same as any
fresh clone without the user's machine. Not a regression; expected in this environment. The
remaining 15: `test_agent_specialists.py` (5), `test_ml_forecast.py` (4), `test_golden.py` /
`test_golden_v2.py` (2), `test_orchestrator_wiring.py` (1), `test_snapshot.py` (2), and
`test_store_security.py::test_aggregate_reads_still_work` (1) — every one needs a real row in a
real table. `test_store_security.py`'s own `pytest.mark.skipif` only checks for `MANIFEST.json`
(committed as provenance metadata, no raw data in it), not for the actual `.duckdb`/`.parquet`
files, so it doesn't skip here — a latent gap in that skip condition, not touched today (pre-Day-8,
out of scope, logged here rather than silently fixed).

**No new ADR** — this is a bug fix to already-shipped Day 7 code, not a new architectural or
build-vs-buy call; it reuses the project's own "lockdown enforced at the engine, never a
mutable runtime toggle" shape from Layer 0 of `docs/specs/text_to_sql_safety.md`, just moved to
the right API surface for it to actually hold under repeated use.

**Verified-local state after the fix: 425/440 pass, 15 fail only for missing local data; ruff
clean; mypy --strict clean on the changed file.** This is this session's working baseline for
Day 8 — the user's own machine, with the real snapshot built, should still read 440/440.

## 22 Oct — Day 8: Addendum A2 §1.1 (fallback model, graceful degradation) + §1.5 (version
pinning into traces)

Closed two A2 §1 gaps the user flagged as overlapping Day 8's own planned work, both on
`LLMClient` (`src/copilot/llm/client.py`), the single chokepoint every LLM call in the project
goes through:

- **§1.1 fallback model:** new `LLMClient._with_fallback()` wraps `complete()`/`structured()`.
  If the primary model's own `_retrying()` budget (4 attempts, already shipped Day 3) is fully
  exhausted on a retryable error and a different `fallback_model` is configured
  (`Settings.fallback_model`, default `None`), one more attempt runs against the fallback with
  its own fresh retry budget — and, for `structured()`, its own fresh repair loop, since a
  fallback model's output shape/wording shouldn't inherit repair turns built against the
  primary's. No fallback configured, or fallback == primary: the primary's exception propagates
  unchanged, exactly Day 3's original behaviour.
- **§1.1 graceful degradation:** `InsightService.vendor_insight()` is the first real call site
  to use the pattern. If narration fails outright even after `LLMClient`'s retries/fallback are
  exhausted (an outage covering every configured model, or a repeatedly-malformed response), it
  now returns `VendorInsight(narration_available=False, narrative=<the deterministic data block
  as JSON>)` and a zeroed `CallMetrics(stop_reason="degraded")` instead of raising — the caller
  still gets the real, correct numbers for a question the data layer could answer on its own
  (A2's own "no fabricated numbers" rule: zeros, not a fake-looking successful `CallMetrics`
  row).
- **§1.5 version pinning:** `CallMetrics` gained `prompt_name`/`prompt_version`/
  `used_fallback_model`. `complete()`/`structured()` both take optional `prompt_name`/
  `prompt_version` kwargs and thread them onto the returned metrics — carried on `CallMetrics`
  itself (not a separate parameter) so they reach every LangSmith trace automatically via the
  existing `process_outputs=mask_run_payload` serialization, no extra wiring. Threaded through
  every real call site: `insights/service.py`, `sql/service.py`, `agents/model_selection.py`
  (×2), `agents/orchestrator.py` (×3), `agents/specialists.py`, `rag/corrective.py` (×3) — all
  13 of them now pass `prompt_name=prompt.name, prompt_version=prompt.version` from the
  `Prompt` object they already load via `copilot.llm.prompts.load_prompt()`.

Two A2 §1.1 items the sprint plan lists as new were actually already shipped Day 3 and were
**not** rebuilt here: timeouts and retries+backoff+jitter (`_retrying()`, already existed) and
schema validation (the structured-output repair loop, already existed). The genuinely new work
this entry covers is only the fallback-model routing and the graceful-degradation return path.

New tests (none of this behaviour existed in the suite before): `test_llm_client.py` —
`test_complete_falls_back_to_configured_model_after_primary_exhausts_retries`,
`test_structured_falls_back_to_configured_model_after_primary_exhausts_retries`,
`test_complete_raises_primary_error_when_no_fallback_configured`,
`test_complete_does_not_fall_back_when_fallback_equals_primary`,
`test_complete_records_prompt_name_and_version_on_metrics`,
`test_structured_records_prompt_name_and_version_on_metrics`; `test_insight_service.py` —
`test_vendor_insight_degrades_gracefully_when_narration_fails`. Full suite after: 435 passed, 15
failed (same pre-existing missing-local-data failures as the previous entry, no regressions);
`ruff check .` clean; `ruff format` clean on every touched file; `mypy --strict` clean (79
source files — tests stay outside strict mypy by design, see `pyproject.toml`).

**No new ADR** — this reuses the project's own established shapes: retry/backoff via tenacity
(Day 3), the `Prompt.name`/`.version` versioning scheme (Day 3), and `CallMetrics` as the one
instrumentation row every call already returns (Day 3). Fallback-model routing and
graceful-degradation-on-exhaustion are new *behaviour*, but not a new *architectural or
build-vs-buy* decision — A2 already made that call; this is its implementation.
