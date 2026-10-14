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
