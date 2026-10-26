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

## 2026-10-17 · Real `vw_PortfolioHealth` run · replacing the synthetic risk-classifier numbers

**Covered:** ran `scripts/train_risk_classifier.py` against a real export of the licensed
`vw_PortfolioHealth` view (SQL Server, your own machine) to get the real accuracy/F1 numbers the
14 Oct entry above flagged as owed. No code changes to `copilot.ml.risk_classifier` -- the
leakage-safe feature set (`LEAKING_FEATURES` = `ProfitMargin`, `MarkupPct`,
`NetMarginAfterExcisePct`, `SalesToPurchaseRatio`) was already fixed on 14 Oct against synthetic
data; this sitting validates that fix against real data rather than diagnosing anything new.

**Export friction (mechanical, not a model problem):** `sqlcmd`'s default text output embeds two
artifacts that break a straight `pandas.read_csv` -- a dash-divider row under the header, and a
trailing `(N rows affected)` summary row -- both stripped with a `Where-Object` regex filter
before training. Also needed `sqlcmd -C` (trust the local self-signed cert) and `uv run python`
instead of a bare `python` call (the project's src-layout `copilot` package is only installed
into the `uv`-managed `.venv`, not onto the system Python resolved by a plain `python` on PATH).

**Real numbers, n=10,495 real SKU rows, label balance 0.303 (30.3% at-risk):**

| combo | accuracy | F1 | n_test | features |
|---|---|---|---|---|
| random_forest_leaky | 0.997 | 0.994 | 2624 | 14 |
| random_forest_safe | 0.952 | 0.919 | 2624 | 13 |
| xgboost_leaky | 0.999 | 0.999 | 2624 | 14 |
| xgboost_safe | 0.971 | 0.953 | 2624 | 13 |

Leaky-vs-safe gap present and large on real data too (RF accuracy 0.997 -> 0.952, F1 0.994 ->
0.919; XGBoost 0.999 -> 0.971, F1 0.999 -> 0.953) -- directionally identical to the synthetic
result above, confirming the 14 Oct leakage fix generalizes rather than being an artifact of the
synthetic fixture's construction.

Top SHAP drivers, leakage-safe Random Forest: `StockTurnover` 0.2809 (dominant), `TotalSalesQuantity`
0.0343, `TotalSalesDollars` 0.0323, `TotalPurchaseDollars` 0.0282, `TotalExciseTax` 0.0208 -- no
margin-family proxy among the top drivers, consistent with the leakage-safe fit actually learning
from operational signal rather than a reconstructed margin.

**These real numbers are now the reported figures** for the SKU risk classifier (see
`docs/PROJECT_PROGRESS.md`), replacing the n=2000 synthetic-fixture numbers from the 14 Oct entry
above, which remain in this log only as the historical record of how the leakage was first
diagnosed and fixed.

**Costs:** $0 -- local SQL Server export + local training, no LLM call, no API key.

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

## 22 Oct — Day 8 steps 3-5: `/ask` SSE endpoint, invite-code + API-key auth, per-user/IP rate
limiting + daily budget (A2 §1.6)

Three closely-coupled pieces, built together because `/ask` literally cannot pick a `Role` to
run a question as without auth resolving one first:

- **Step 3, `/ask`:** `Orchestrator.answer()` was refactored into a two-line wrapper around a
  new generator, `stream_answer()` (`src/copilot/agents/orchestrator.py`) — all of `answer()`'s
  own logic (input-gate check, run the graph, detect a paused approval-gate interrupt, record
  spend) moved there unchanged, confirmed by every pre-existing orchestrator test passing
  unmodified plus new tests on the generator itself. `stream_answer()` switches from
  `graph.invoke()` to `graph.stream(..., stream_mode="updates")` — confirmed by a throwaway
  probe script (not kept) to yield one `{node_name: partial_state}` dict per node in execution
  order, and an `"__interrupt__"` key in place of a node name when `_approval_gate` pauses —
  and yields a `StreamEvent(type="node", node=<name>)` per node, then one trailing
  `StreamEvent(type="result", result=<OrchestratorResult>)`. `POST /ask`
  (`src/copilot/api/main.py`) hand-rolls plain SSE (`event: <type>\ndata: <json>\n\n` per
  `StreamEvent`) over `StreamingResponse` — no `sse-starlette` dependency added, since the
  whole stream is "one JSON object per typed event," nothing a 6-line generator doesn't already
  cover.
- **Step 4, auth:** `src/copilot/api/auth.py`'s `AuthStore` — invite-code (for a human,
  self-service, single-use) + API-key (long-lived, admin-issued directly for a programmatic
  caller) authentication, both `secrets.token_urlsafe(24)` hashed with SHA-256 before ever
  touching disk (`data/auth/auth_store.json`, added to `.gitignore`); the raw value is returned
  exactly once, at issue/redeem time, by design — there is no "show my key" endpoint. There is
  also deliberately no HTTP endpoint that *mints* an invite or key, only `POST /auth/redeem`,
  which *exchanges* one — minting happens out-of-band via the new `scripts/
  issue_invite_code.py`, run by whoever administers the deployment.
- **Step 5, rate limiting:** `src/copilot/api/rate_limit.py` adds per-identity (API-key) and
  per-client-IP request limits plus a per-identity daily cost budget, on top of (not instead
  of) Day 7's `InputGate`, which only limits per-*role* — one noisy API key would otherwise
  share a `viewer`-wide bucket with every other viewer. `RequestRateLimiter` reuses
  `InputGate.RateLimiter`'s exact sliding-window mechanism, just keyed by an arbitrary identity
  string; `DailyBudgetTracker` is a thin wrapper around `SpendTracker` itself (its `role: str`
  param is really just a dict key), pointed at its own file so per-user and per-role totals
  never collide.
- **Wiring:** `src/copilot/api/dependencies.py` is the new glue — `get_orchestrator()` builds
  the real `Orchestrator` lazily, on first `/ask` call (`@lru_cache`'d), reusing `scripts/
  run_orchestrator_golden.py`'s own real-service wiring rather than re-deriving it, specifically
  so `/health`/`/version` (meant to be dependency-free liveness checks, per that module's own
  Day 2 docstring) never fail to start a process missing a real `ANTHROPIC_API_KEY` or
  snapshot/Chroma index. `require_role(*allowed)`/`require_any_role` resolve a `Principal` from
  the `Authorization` header; `enforce_rate_limits` runs the three new checks after that,
  before the Orchestrator (or even the input gate) ever sees the request.

Added `"src/copilot/api/*" = ["B008"]` to `pyproject.toml`'s ruff per-file-ignores — FastAPI's
own DI idiom (`param: T = Depends(get_t)`) is exactly what ruff's B008 generally guards against
(a function call as a default value), and FastAPI's own docs recommend disabling it for files
that use `Depends()` this way.

New tests: `test_api_auth.py` (7), `test_api_rate_limit.py` (5), `test_api_ask.py` (6, against
the real `TestClient` + `app.dependency_overrides` — the standard FastAPI testing idiom, the
only way `/ask`/`/auth/redeem` are testable without the real snapshot/Chroma/API key
`get_orchestrator` would otherwise need), plus 4 new `stream_answer()` tests on the Orchestrator
itself. Full suite: 457 passed, 15 failed (same pre-existing missing-local-data failures, no
regressions); `ruff check`/`format` clean; `mypy --strict` clean (83 source files — tests stay
outside strict mypy by design).

**No new ADR** for auth/rate-limiting's *shape* — both reuse this project's own established
"small JSON file, loaded fresh, hashed secrets" pattern (`SpendTracker`, `copilot.guardrails.
audit_log`) rather than inventing a database or a new secrets format; a real production
deployment would likely want a managed secrets store and a shared (not per-process) rate
limiter, noted here as a known limitation rather than silently assumed away, same posture
`RequestRateLimiter`'s own docstring already takes. The `/ask` SSE *format* itself (hand-rolled,
not a library) is a design choice worth a sentence, not a decision with real alternatives
weighed — covered in this entry and the `main.py` docstring instead.

## 22 Oct — Day 8 step 6: the CI eval gate (A2 §1.3)

`evals/thresholds.yaml` + `scripts/run_eval_gate.py`, wired into a new `eval-gate` job in
`.github/workflows/ci.yml` (PRs targeting main only, not every push — the existing `checks` job
already lints/types/tests on every push; this is the extra pre-merge bar).

**Deterministic-first, for real, not just in name:** the gate's hard floor is `uv run pytest`
(zero real LLM calls anywhere in that suite — every LLM-dependent path is exercised against
`tests/fakes/anthropic_fakes.py`) failing on anything outside a fixed, named set of 15 test ids
(`_KNOWN_MISSING_DATA_FAILURES`) that always fail in an environment with no local
`data/snapshot/` — this project's own licence rule (the purchased workbook is never committed,
exposed, or reconstructed outside your own machine) means that's every environment this repo's
actual GitHub Actions run will ever see. Confirmed against a real run in this cloud session:
`15 failed, 457 passed`, all 15 inside the known set — deterministic layer reports PASS.

**The `llm_judged` layer (text-to-SQL exec-accuracy/leakage-free, RAG faithfulness/context-
recall, Model Selection task-type/reasoning-grounded, Orchestrator plan-coverage/verified-rate,
thresholds in `thresholds.yaml`) only runs when a real `ANTHROPIC_API_KEY` *and* the real
snapshot/Chroma index are both present** — confirmed by running the gate script for real in
this session: it correctly printed `LLM-judged evals: SKIPPED (no ANTHROPIC_API_KEY
configured)` and exited 0, rather than either fabricating a pass or failing the gate over
infrastructure the licence rule means this environment can never have. Hardened one real gap
found while reasoning through the CI wiring, not yet hit in practice: `.github/workflows/
ci.yml` passes `secrets.ANTHROPIC_API_KEY` through as an env var unconditionally (harmless if
unset) so this layer activates automatically the day this repo's own CI is ever given a real
key and a real, non-sensitive snapshot — but an *unset* GitHub secret resolves to an *empty
string* env var, not an absent one, and pydantic-settings reads that as `SecretStr("")`, not
`None`. `_real_infra_available()`'s check was `is None` only, which would have missed this and
let `LLMClient()` raise an unhandled `LLMCallError` deeper in the run instead of this function's
own clean, reported skip. Fixed by also checking `.get_secret_value()` is non-empty, confirmed
by re-running the gate script after the fix.

**Verified the gate actually fails on a real regression, not just that it passes when
everything's fine:** temporarily broke one assertion in `tests/test_api_auth.py` (`role ==
"analyst"` -> `role == "nope"`), ran the gate, confirmed it printed `GATE FAILED: 1 unexpected
test failure(s), not in the known missing-local-data set` and exited 1 (verified via a separate
`$?` check — an earlier attempt piped the gate's output through `tail` and read `$?` from
`tail`, not the gate script, which silently misreported success; caught by checking the exit
code a second way rather than trusting the first result), then reverted the test file with `git
checkout` and re-ran the gate clean to confirm it returned to `457 passed` / exit 0.

Added `max_llm_budget_usd` enforcement via a new `_CostTrackingLLMClient` wrapper in the gate
script — accumulates `cost_usd` across every `complete()`/`structured()` call (duck-typed, no
existing evaluator signature touched, since `rag_quality.faithfulness`/`context_recall` and
`model_selection_quality.reasoning_grounded` already discard the `CallMetrics` their own judge
calls return internally) and refuses a new call once the running total reaches the cap — same
"can only act on *past* spend, not this call's own cost before it runs" honesty
`copilot.guardrails.input_gate.SpendTracker`'s own daily cap already lives with.

**No new ADR** — reuses this project's own established eval-suite functions
(`copilot.evals.evaluators`/`rag_quality`/`model_selection_quality`/`orchestrator_golden`, all
Day 3-6 work) and the existing CI job shape (`astral-sh/setup-uv`, `uv sync --frozen`, same
runner); the only genuinely new mechanism is `_CostTrackingLLMClient`, a thin instrumentation
wrapper, not an architectural decision.

## 22 Oct — Day 8: determinism note (Addendum A2 §1.7)

**What:** `docs/determinism.md` -- the "just a doc paragraph" A2 asked for, explaining which
parts of this system are deterministic (Guardian, input gate, SQL validator, auth/rate-limit,
`execution_accuracy`/`leakage_free`) and which are inherently not (anything behind
`LLMClient.complete()`/`.structured()` -- planning, drafting, verifying, the LLM-judged evals),
and how each existing mechanism (forced structured output, the repair/redraft loops, the
Guardian's unconditional post-draft run, golden-set numeric tolerance, prompt version pinning
from A2 §1.5) narrows the impact of that non-determinism rather than pretending it away. No new
mechanism, no code change -- pure documentation, written after re-reading `docs/TRADEOFF_LOG.md`
(which already tracks "temperature change" as a trigger category and has its own "Open
measurement debt" section listing which Day 7 changes are deterministic) and `copilot.llm.client`'s
module docstring (confirms no `seed`/`temperature`/`top_p`/`top_k` on this model generation,
`effort` as the nearest per-call lever) as the two existing sources of truth it had to stay
consistent with.

**No new ADR** -- this is a documentation deliverable, not a design decision; nothing in the
system's behavior changed.

## 22 Oct — Day 8 step 7: Postgres checkpointer

**What:** the orchestrator's checkpoint store can now be Postgres instead of local SQLite, for
real multi-replica/redeploy-safe durability, while every existing caller and every test keeps
working unchanged.

- `Orchestrator.__init__` gained a `checkpointer: BaseCheckpointSaver[str] | None` parameter
  alongside the existing `checkpoint_path: str | None` -- pass either, or both (`checkpointer`
  wins). The module stays storage-agnostic: it only ever calls the `BaseCheckpointSaver`
  interface, never imports `psycopg` or anything Postgres-specific. `checkpoint_path` is
  unchanged and still the simplest path for local dev and every pre-existing test.
- New `Settings.checkpoint_database_url: SecretStr | None` (default `None`).
- New `copilot.api.dependencies._build_checkpointer()`: `None`/empty DSN -> the existing local
  `SqliteSaver(CHECKPOINT_PATH)`; a real DSN -> `PostgresSaver` over a `psycopg_pool.
  ConnectionPool` (a pool, not a single `Connection` -- this object is one process-lifetime
  singleton shared by every concurrent `/ask` request, and a single psycopg `Connection` isn't
  safe for that). `get_orchestrator()` now calls this instead of hardcoding `checkpoint_path`.
  `.setup()` runs LangGraph's own idempotent migration on every start-up.
- New dependencies: `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`.
- New `infra/local/compose.yaml` -- a local-only Postgres container (never used by CI or the
  real deploy job) for exercising the Postgres branch by hand; `.env.example` documents
  `CHECKPOINT_DATABASE_URL` and points at it. `docs/HANDOFF.md`'s action checklist got one more
  optional row for a real prod Postgres instance + the SSM parameter.

**Verification:** `uv run mypy`/`ruff check`/`ruff format --check` all clean; full `uv run
pytest -q` -- 461 passed (the pre-existing 15 known missing-data failures, unchanged, plus 4 new
tests: `test_checkpointer_param_takes_priority_over_checkpoint_path` in `test_orchestrator.py`
(two real `SqliteSaver`-backed files, proving `checkpointer` wins and `checkpoint_path`'s file is
never even created) and three in the new `tests/test_api_dependencies.py` covering
`_build_checkpointer`'s three branches (unset, empty string -- the same pydantic-settings
empty-env-var gotcha the eval gate already had to guard against for `ANTHROPIC_API_KEY` -- and a
real DSN, the last via monkeypatched `ConnectionPool`/`PostgresSaver` fakes since there's no live
Postgres in this environment); re-ran `scripts/run_eval_gate.py` end to end, still exit 0.
**Not verified against a live Postgres instance in this environment** -- no Docker daemon
available here (`docker ps` fails: no `/var/run/docker.sock`) -- so the Postgres branch itself is
proven by test, by API inspection (`PostgresSaver.__init__`'s type signature confirmed to accept
a `ConnectionPool`, not just a `Connection`), and by `.setup()`/`ConnectionPool` being exactly
the documented langgraph-checkpoint-postgres API, not by an actual round-trip against a running
database. Whoever runs this against `infra/local/compose.yaml` first should treat that as the
real first integration test of this path, not a formality.

**No new ADR** -- Postgres itself was the brief's own instruction (A2/Day-8 scope), not a choice
made among alternatives here; the design reuses the checkpointer-as-injected-dependency shape
Day 6 step 6 already established (the Orchestrator takes a storage object/path, never builds
its own notion of "the" checkpoint store), just widened from one concrete type (`SqliteSaver`
over a `sqlite3.Connection`) to any `BaseCheckpointSaver`, with the concrete choice pushed to the
caller -- not a new pattern.

## 22 Oct — Day 8 step 7: minimal UI, plus the missing /ask/approve endpoint

**What:** a minimal, framework-free UI for the Copilot, and the one HTTP endpoint it needed
that didn't exist yet.

- **Found while building the UI, not before:** `Orchestrator.resume_approval()` (Day 7 step 5)
  had no HTTP route. Every approval-gate test exercised it as a direct Python call; nothing
  outside the process could ever actually approve, edit or reject a paused Action draft. Added
  `POST /ask/approve` in `src/copilot/api/main.py` -- `ApprovalRequest(thread_id, decision,
  edited_answer)`, gated by a new `require_approver_role = require_role("approver", "admin")`
  dependency (a separate factory call from `/ask`'s `require_any_role`, deliberately -- the two
  routes allow different role sets). Maps `PermissionError` -> 403, `RuntimeError` (no
  checkpointer) -> 409.
- `GET /` serves `src/copilot/api/static/index.html`; `/static/*` is a mounted `StaticFiles`
  directory for `style.css`/`app.js`. One page: a credentials panel (redeem an invite, or paste
  an existing key, saved to `localStorage`), a chat box, a live agent-status strip built from
  `StreamEvent(type="node")` events, result badges (verified, Guardian escalated/blocked,
  pending-review with its `review_id`, pending-approval), a citations section built from
  `OrchestratorResult.results` (every real field already on `AgentResult` -- no new data
  invented for the UI), and an approval panel that calls the new endpoint.
- `/ask`'s SSE stream is parsed by hand in `app.js` (`response.body.getReader()`, split on blank
  lines) because `EventSource` cannot set a custom `Authorization` header and this project
  authenticates with a bearer API key, not a cookie.
- Confirmed the static files are actually bundled into the package: built a real wheel with
  `uv build --wheel` and inspected its file list -- `copilot/api/static/{app.js,index.html,
  style.css}` are present, so `[tool.hatch.build.targets.wheel]`'s existing `packages =
  ["src/copilot"]` needed no change.

**Verification:** `uv run mypy`/`ruff check`/`ruff format --check` clean; full `uv run pytest -q`
-- 465 passed (same 15 known missing-data failures, unchanged), 4 new tests in
`tests/test_api_ask.py`: an approver successfully resuming a paused Action draft end to end
through `/ask` then `/ask/approve`, a non-approver (`analyst`) getting a 403 from the same
endpoint, and `GET /` / `GET /static/app.js` actually serving the page and its script. Also
started the real server (`uv run uvicorn copilot.api.main:app`) and hit `/`, `/static/app.js`,
`/static/style.css`, and `/openapi.json` with `curl` by hand -- all 200, and the schema lists
`/ask/approve` alongside the pre-existing routes.

**No new ADR** -- `/ask/approve` reuses the exact `require_role(*allowed)` factory + `Depends()`
shape `/ask`/`enforce_rate_limits` already established (Day 8 step 4), just with a different
allowed-role set; the UI is a static-files mount, the simplest option for "serve one HTML page
and its JS/CSS from the same process," not a build-vs-buy decision between frameworks.

## 22 Oct — Day 8 step 7 wrap-up: progress docs, version bump, v0.1.0

**What:** `docs/PROJECT_PROGRESS.md` brought current through all of Day 8 (sprint status table,
a new Day 8 checklist mirroring Day 7's format, Results rows for the eval gate/Postgres/UI work,
Decisions noting ADR-006 is now resolved and why Day 8 needed no new ADR, Costs to date, and an
honest "Next step" naming exactly two things left: verifying the Postgres path against a real
database, and real-key runs that only add numbers to already-tested code). `pyproject.toml`
bumped `0.0.1` -> `0.1.0`, matching the sprint brief's own Day 8 scope ("...then release
v0.1.0"), `uv sync` run to update `uv.lock`'s matching entry.

**Mistake, caught by the test suite itself:** the version bump broke
`tests/test_api.py::test_version_reports_git_sha`, which had `assert body["version"] ==
"0.0.1"` hardcoded -- exactly the kind of test that looks like it's checking something but was
really just checking that nobody ever changed the version number. Fixed by reading the expected
value from the installed package's own metadata (`importlib.metadata.version(...)`, the same
call `/version` itself uses) instead of a literal string, so this test checks the real
behaviour (the endpoint reports whatever's actually installed) and won't need touching at the
next version bump either.

**Verification:** full `uv run pytest -q` back to 465 passed / 15 known failures (the fixed
test included); `ruff check`/`ruff format --check`/`mypy` all clean.

**No new ADR** -- a progress-doc update and a version-number bump are not architectural
decisions.

## 22 Oct — v0.1.0: pushed main, tag blocked by this session's GitHub permissions

`git push origin main` succeeded (commit `ff65007` and everything before it in this sitting is
now on GitHub). The local annotated tag `v0.1.0` (full release note on the tag itself --
`git tag -l -n99 v0.1.0`) could not be pushed from here: `git push origin v0.1.0` and
`git push origin refs/tags/v0.1.0` both returned HTTP 403, and the two REST-API fallbacks tried
next (`gh api .../releases`, `gh api .../git/refs`) were both explicitly refused by this
session's own GitHub proxy -- "Creating, editing, or deleting releases is not permitted for
this session type" and "Write access to this GitHub API path is not permitted through this
proxy," respectively. Not a credentials or network problem; a deliberate restriction on this
session type, not worth retrying further. **You'll need to push the tag yourself**: from your
own machine, `git fetch && git push origin v0.1.0` (the tag already exists locally in this
container's clone's history once pulled) -- or simplest, just re-create it: `git tag -a v0.1.0
-m "<message>" && git push origin v0.1.0` from a machine with normal push access, or create the
release directly on GitHub's web UI, pointing at commit `ff65007`.

## 22 Oct — Day 9 step 1: template-based question->SQL pair generator (B7)

`copilot.sql.pair_generation` (pure, testable: `generate_candidates()` builds the template x
parameter grid against a connection without executing anything; `verify_and_filter()` runs two
separately-counted filters -- execution against the real snapshot, then the real
`copilot.sql.validator.validate()` safety layers) plus `scripts/generate_sql_pairs.py`, a thin
CLI wrapper (same shape as `scripts/train_risk_classifier.py`: real logic in the package, the
script just wires it to the real snapshot and writes the output file) that needs a built
snapshot to run for real -- same licence rule as every other "real data" script in this repo
(ADR-002). Real vendor names are read from the connected database at generation time, never
hardcoded.

Six template families (single-vendor lookup across 7 headline columns, pairwise comparison,
top-N ranking both directions, portfolio-level aggregation, monthly-demand trend, health-mix
breakdown), each skipped automatically if its table isn't present in the connection -- lets the
9 new unit tests run against a tiny synthetic in-memory DuckDB fixture (invented vendor names
and numbers, real table/column shape -- the same "schema, not licensed data" convention
`tests/test_sql_validator.py` already uses) with only 3 of the real tables created, rather than
needing every one of them.

**Why two filters, not one:** the spec's own bar for Day 9 is "keeps only pairs that execute
correctly," but execution alone doesn't catch a template whose shape the project doesn't want
to teach a fine-tuned model to produce (e.g. one the validator would reject or cap). Counting
them separately (`FilterReport.execution_failed` / `.validator_failed`) means a future run's
printed breakdown tells you *why* a candidate was dropped instead of just a shrunk total.

**Correction, same session, once the real workbook was uploaded to this chat (not committed --
see the entry below):** the paragraph originally here said this needed a run on your own
machine, since `Vendor_Summary.xlsx` can never enter this repo or (it was assumed) this cloud
sandbox. That second half was wrong -- the licence rule (ADR-002) is about never committing the
raw workbook to *Git*, not about the file never reaching this session. Uploaded directly to the
chat (never written to the repo, never committed), it ran for real right here: `uv run python
scripts/generate_sql_pairs.py --target 400` against the real snapshot produced
**1016 candidates, 0 execution failures, 0 validator failures, all 1016 passed both filters**,
sampled down to the requested 400 (by category: 285 lookup, 51 comparison, 43 trend, 21
aggregation). Zero failures on both filters is itself a real result, not a shortfall: it says
the templates and the real safety validator agree on every shape this run generated. Real
output committed: `evals/datasets/sql_pairs_v1.jsonl` + its manifest -- same "vendor-level
aggregates only, no SKU-level columns" posture `golden_v1`/`golden_v2` already established as
safe to commit (RAID R7), not a new exception.

**Verification (at the time this module was first written, before the real run above):**
`uv run pytest tests/test_generate_sql_pairs.py -v` -- 9 passed. Full suite: 474 passed (465 +
these 9), same 15 known missing-snapshot failures as every prior day. `ruff check .` and
`uv run mypy` both clean (added file-scoped `S608`/`S311` ignores to `pyproject.toml` for this
module and its script/test -- the whole point of the module is building parameterized SQL
template strings with a non-cryptographic RNG for training-data sampling, not a security
boundary; every kept string is re-validated by the real safety validator before being written
out).

**No new ADR** -- reuses the existing schema/policy/validator modules exactly as
`TextToSqlService` already does; the "real logic in the package, thin script wrapper" shape
follows `train_risk_classifier.py`'s established pattern, not a new build-vs-buy decision.

## 22 Oct — Day 9 step 4: Vendor Analytics MCP server (never cut, per the sprint's own list)

`copilot.mcp.server` -- 3 read-only tools (`vendor_metrics`, `portfolio_summary`,
`ask_vendor_question`) over `mcp.server.fastmcp.FastMCP`, stdio transport. Added `mcp` as a new
dependency, pinned `>=1.2.0,<2.0.0`: the unpinned resolve picked `mcp` 2.3.0, whose `FastMCP`
class was renamed `MCPServer` with a materially larger constructor (`auth_server_provider`,
`resource_security`, `subscriptions`, `middleware`, ...) -- released after this project's
working knowledge cutoff, so building against its real shape untested would have been guessing.
Pinning to the 1.x line (resolved to `1.30.0`) keeps the `FastMCP` API that MCP Inspector's own
docs and Claude Desktop's setup guides assume; "remote MCP with API-key or OAuth auth" is
already the depth-track item that would revisit this (X1 #5), not Day 9's.

**Why every tool is hardcoded to `role="viewer"` rather than accepting a `role` argument:** an
MCP tool parameter is just a string the calling client chooses to pass -- accepting `role` here
would let any caller claim `role="analyst"` and read confidential data with no authentication
behind that claim, exactly the privilege-escalation vector this project's least-privilege
posture (R11, ADR-006) exists to close everywhere else. Documented in the module's own
docstring so the reasoning doesn't need rediscovering at the X1 #5 remote-MCP-auth point, where
an actually-authenticated role should start flowing in.

**`ask_vendor_question` still goes through the mandatory Guardian pass** (docs/adr/
006-guardian-design.md) before returning an answer -- MCP is a new path into the system that
didn't exist before Day 9, so it gets the same "no path to the end node skips the Guardian"
treatment Day 7's topology test enforces for the Orchestrator's own graph, via a small
`_ToolReviewable` duck-typed to the Guardian's `_Reviewable` Protocol (no fake
`OrchestratorResult` needed -- same reason the Protocol exists in the first place).

**A real finding worth recording, not quietly working around:** the first implementation
rendered SQL result rows as `"ColumnName: value"` pairs (e.g. `"VendorName: ACME BEVERAGES,
TotalRevenue: 100000.0"`). Testing that end to end (`tests/test_mcp_server.py`, fakes --
no real API key) through the real Guardian showed TWO real false positives from Presidio's
generic recognizers, not an MCP-specific bug: (1) a bare 6+ digit number matched
`US_DRIVER_LICENSE` -- fixed by formatting numbers with thousands separators (`100,000.0`, not
`100000.0`); (2) an all-caps multi-word value immediately followed by a colon then another
field (`"VendorName: ACME BEVERAGES, TotalRevenue: ..."`) made the vendor name itself match
`LOCATION` via Presidio's spaCy-backed NER -- fixed by rendering the first column as `"For
ACME BEVERAGES: TotalRevenue 100,000.0"` instead (confirmed empirically which exact phrasing
stops triggering it, not guessed). Both fixes are recorded in `_format_rows`'s own docstring.
Left as Guardian's call rather than bypassed: if Presidio flags something, Guardian redacts --
that's the system working as designed, even when the specific trigger is a false positive;
the fix here is choosing an answer format that doesn't manufacture one, not overriding the
verdict.

**Tested over the real stdio protocol, not just as plain Python function calls:** MCP Inspector
(`npx -y @modelcontextprotocol/inspector --cli`) was available in this sandbox (Node 22) and
used for a real `tools/list` (all 3 tools, correct schemas) and two real `tools/call` round
trips: `portfolio_summary` against this sandbox's absent snapshot (clean `isError: true` with
the real DuckDB catalog error, not a crash) and `ask_vendor_question` with no API key configured
(clean `isError: false`, structured `{"answered": false, "error": "..."}`, no fabricated
answer). **Not run here, genuinely needs your machine:** Claude Desktop itself (no desktop app
in this cloud sandbox) and both tools against the real, built snapshot (same licence-gap as
Day 9 step 1 and every other "real data" item) -- `docs/COMMANDS.md`'s new Day 9 section has
the exact commands for both.

**Verification:** `uv run pytest tests/test_mcp_server.py -v` -- 10 passed (3 deterministic-tool
tests, 1 withheld-below-min-k test, 1 unknown-vendor test, 2 `ask_vendor_question` tests against
fakes, 3 `_format_rows` regression tests covering the Presidio finding above). Full suite: 484
passed (474 + these 10), same 15 known missing-snapshot failures as every prior day. `ruff
check .`, `ruff format --check` and `uv run mypy` all clean.

**No new ADR** -- every tool wraps an existing, already-tested service exactly as it already
behaves (`store.connect()`, `TextToSqlService.answer()`, `Guardian.review()`); the one real
decision (pinning `mcp<2.0`) is a dependency-version choice with a one-line reason, not an
architectural trade-off between real alternatives.

## 22 Oct — real snapshot built in this cloud session; both known gaps narrowed to one

You uploaded `Vendor_Summary.xlsx` directly to this chat (not committed, never written into the
repo -- `scripts/build_snapshot.py` read it straight from the chat's attachment path). This
corrects something stated incorrectly earlier today (see the Day 9 step 1 entry above): the
licence rule (ADR-002) says the raw workbook never enters *Git*, not that it can never reach
this session -- uploading it to the chat and this cloud sandbox are different things, and only
the first one is restricted.

`scripts/build_snapshot.py` ran for real: 126 vendors across every vendor-grain table (matches
every row count already documented), 1400 vendor-month rows, 399 vendor-health rows -- exact
match against `data/snapshot/MANIFEST.json` already committed to the repo (`git diff` against
it: empty). `data/snapshot/*.parquet` and `*.duckdb` stayed exactly where the licence rule
wants them: gitignored, confirmed with `git status --short data/snapshot/` (nothing to commit).

**Full suite re-run with the real snapshot present: 499 passed, 0 failed** -- the 15 tests that
failed in every environment without a snapshot (`test_canonical_metrics`,
`test_manifest_matches_files`, both golden sets' re-execution tests, the ML forecast and agent-
specialist tests, `test_aggregate_reads_still_work`) all pass for real now, not just
differently-explained failures. Spot-checked two canonical numbers directly against the golden
set rather than trusting the green suite alone: DIAGEO's total revenue ($68,739,834.97) and
MARTIGNETTI's blended margin (31.98%) both matched exactly before the snapshot was even built
(computed straight from an earlier raw CSV export of the same underlying data), then again
through the real `vendor_metrics` MCP tool afterward.

**Both of Day 9's "never run for real" caveats are now addressed, with one real one left:**
`scripts/generate_sql_pairs.py` ran for real (separate entry above) and the MCP server's
`vendor_metrics`/`portfolio_summary` tools were re-verified over real stdio against real data
(DIAGEO's exact figures came back through the actual MCP Inspector round trip). `ruff check .`
and `uv run mypy` both clean against the full tree. **Still genuinely missing, unrelated to
data:** no `ANTHROPIC_API_KEY` in this session, so `ask_vendor_question`'s real-LLM path, the
CI eval gate's `llm_judged` layer, and the Postgres-checkpointer live round trip are still
exactly the gaps they were before -- a missing credential, not a missing dataset, and the two
are genuinely independent of each other.

**One real-world data-quality observation surfaced by the real run, not a bug:** vendor names
in the real data are inconsistently cased (`"TY KU LLC"` vs `"Dunn Wine Brokers"`, both from the
same `VendorName` column) -- confirmed by direct query, not assumed. `copilot.sql.pair_
generation` already handles this correctly (it round-trips whatever casing is actually stored,
never re-cases a value used in a `WHERE` clause), but it's worth knowing if a future agent or
prompt ever assumes vendor names are uniformly upper-case.

**No new ADR** -- this is a data-provisioning correction and a verification run, not an
architectural decision.

## 23 Oct — Day 9 steps 2-3, 5-6: QLoRA fine-tuning benchmark, scaffolded (B7, "Option A")

Scope: the Colab notebook, the comparison harness, and the results/ADR templates for the
base-vs-few-shot-vs-QLoRA fine-tuning benchmark -- everything except the actual training run
and real numbers, which need a GPU this cloud sandbox doesn't have. User explicitly chose this
("Prooceed with option A") over pausing at the GPU gap.

New top-level `finetuning/` directory, deliberately outside `src/`/`scripts/` (and outside
`pyproject.toml`'s deployed `dependencies` and `mypy`'s `files=["src","scripts"]`), same
isolation judgment already applied to `mcp<2.0` pinning and `infra/local/`'s Docker-only
pieces -- see `finetuning/README.md` for the full reasoning. Contents:

- `README.md` -- scope, why the isolation, why no real run happened here, base-model choice
  with 3 cited sources (chose **Qwen2.5-1.5B-Instruct**, Apache 2.0 -- researched via web
  search rather than relied on from training knowledge, since this is a fast-moving area), and
  step-by-step run instructions.
- `requirements-colab.txt` -- the Colab-only pip list (torch, transformers, peft,
  bitsandbytes, trl, accelerate, datasets, duckdb), loosely pinned (minimums only) so it
  doesn't fight Colab's own base-image CUDA versions.
- `day9_qlora_colab.ipynb` -- 19-cell notebook: installs deps, uploads
  `evals/datasets/sql_pairs_v1.jsonl` + `MANIFEST.json`, rebuilds the schema card and prompt
  template from the manifest (not a hand-copied schema), 85/15 train/held-out split
  (seed=42, writes `held_out.jsonl`), loads the base model in 4-bit NF4 with a LoRA adapter
  (r=16, alpha=32, standard QLoRA defaults -- no hyperparameter sweep, out of scope for a
  Day-9 benchmark), tokenizes with completion-only loss (prompt tokens + padding masked to
  -100, so the loss only ever grades the SQL tokens), trains (3 epochs, batch 4 x grad-accum
  4, bf16), saves the adapter, runs a 3-example sanity check, and downloads the adapter zip +
  `held_out.jsonl`. Built via a one-off generator script in the scratchpad (not committed --
  the repo gets the resulting `.ipynb` only) and validated with `nbformat.validate()`.
- `eval_compare.py` -- the comparison harness. Re-implements (standalone, so it can run in
  Colab without the private repo cloned) the project's own existing "re-execute SQL, round
  floats to 2dp, compare row-for-row" convention from `copilot.evals.golden.run_rows()`/
  `verify()` -- confirmed by reading those functions before writing this one, not invented
  fresh. Evaluates base (zero-shot), base + few-shot (lexical Jaccard retrieval, same shape as
  production's `copilot.sql.examples.retrieve_examples`), and the QLoRA-adapted model against
  `held_out.jsonl`, each executed against the real snapshot and compared to the ground-truth
  SQL's own freshly-executed rows. Optional `--include-frontier` row (needs
  `ANTHROPIC_API_KEY`) is the sprint's own named cut-first item. Reports executable rate,
  execution accuracy, and mean latency per variant, printed as a table and written to JSON.
  `ruff check .` clean (added a scoped per-file-ignore for the notebook's S311/I001, same
  precedent as `scripts/generate_sql_pairs.py`'s own S311 ignore -- see `pyproject.toml`).
- `results_template.md` -- empty results table + how-to-read-the-numbers notes, explicitly
  marked "template, not a result."
- `docs/adr/007-finetuning-outcome.md` -- status PENDING, decision framework spelled out
  (three conditions: clear accuracy win over both base variants beyond split-seed noise,
  executable rate at least matching the few-shot baseline, acceptable latency), decision and
  consequences left as fill-in-after-running.

**Still genuinely not run for real, same honest gap as before:** no GPU in this sandbox. The
notebook, the harness, and the templates are ready; the actual numbers, the actual adopt/don't
decision, and the actual results-table fill-in all still need the user to open the notebook in
Colab (free T4 tier is enough) and run `eval_compare.py` afterward. This is recorded here and
in `finetuning/README.md` rather than implied otherwise.

## 23 Oct — real root cause of the CI "Build image" failure (not a new bug, a week-old one)

User reported ~40 GitHub failure notifications. Checked `gh run list`: both `ci.yml` jobs
(`checks`'s Format check, `image`'s Build image) had been failing on **every** push since
~14 Oct -- the volume was that one standing pair of failures repeating, not 40 separate bugs.

**Format check -- fixed, verified:** 11 files had drifted from `ruff format`'s output (10
pre-existing, unrelated to any one day's work, plus the Day 9 notebook's code cells added
today). `uv run ruff format .` reformatted all 11; `ruff check .`, `mypy`, and the full test
suite (499 passed) stayed clean. Pushed separately from the root-cause fix below.

**Build image -- real cause found from the actual log, not guessed.** This sandbox can't fetch
GitHub Actions' raw logs directly (`results-receiver.actions.githubusercontent.com` and the
Azure blob-storage log URL it redirects to are both outside this session's network allowlist --
confirmed via direct `curl`, not assumed), so the user pulled the "Build image" step's own
output from github.com and pasted it in. The real error:

```
error: Failed to install: torch-2.14.1-...-x86_64.whl (torch==2.14.1)
  Caused by: failed to copy file ... libtorch_cpu.so ...: No space left on device (os error 28)
```

Not a network/download failure at all -- the runner's disk filled up. Root cause, traced from
the log's own download list: `sentence-transformers` (a direct dependency, used for RAG
embeddings since Day 5) requires `torch`, and PyPI's default linux wheel for `torch` pulls in
the *entire* NVIDIA CUDA toolkit as separate packages (`nvidia-cublas` 403MB, `nvidia-cudnn-
cu13` 527MB, `nvidia-cusolver` 191MB, `nvidia-cufft` 204MB, `triton` 236MB, `nvidia-nccl-cu13`
206MB, `nvidia-cusparselt-cu13` 162MB, more) -- several GB on top of torch's own 528MB -- even
though this API runs CPU-only in production and never touches a GPU at inference time.

**Fix:** declared `torch` as a direct dependency (required for `[tool.uv.sources]` to apply --
it only overrides a source for a package already in the project's own dependency graph, not an
arbitrary transitive one; confirmed by testing both ways) and pointed it at PyTorch's own
CPU-only wheel index (`download.pytorch.org/whl/cpu`), which has no CUDA packages at all. Same
"don't carry a dependency this environment can't support" judgment already applied to keeping
GPU/ML training deps out of `pyproject.toml` entirely (`finetuning/README.md`) -- here applied
to a dependency that does need to ship, minus its GPU half.

**Known limitation, stated plainly:** `uv.lock` is *not* regenerated as part of this fix.
`download.pytorch.org` is outside this cloud sandbox's own network allowlist (confirmed with a
direct `curl` -- 403 at the proxy level, same kind of restriction as the Actions-log fetch
above), so `uv lock` cannot complete here. The `pyproject.toml` change is pushed; `uv.lock`
still needs regenerating from a machine with normal internet access (the user's own laptop),
then committing on top. Until that happens, `uv sync --frozen` correctly reports the lock file
as out of date -- an expected, named gap, not a new failure mode.

**Follow-up, same day:** `uv.lock` regenerated on the user's laptop (normal internet, so
`download.pytorch.org` was reachable there) -- confirmed removing every CUDA package except
one (`nvidia-nccl-cu13`, pulled in separately by `xgboost`, much smaller, left as-is). A
"fetch first" push rejection while reconciling the laptop's commit with this session's own
pushed commits was normal git divergence-protection, not data loss -- resolved with a plain
`git pull` + `git push`.

## 23 Oct (cont.) -- the two real bugs behind the "Tests" step's 15 failures

With Format check and Build image both finally green, the user hit a third failure: CI's
"Tests" step reporting 15 failed, 484 passed, every failure a
`duckdb.CatalogException: Catalog Error: Table with name <vendor table> does not exist!` --
found from the actual uploaded CI log, not guessed.

**Bug 1 -- `.env` fallback made `monkeypatch.delenv` a no-op.**
`test_ask_vendor_question_reports_a_clean_error_with_no_api_key` in `test_mcp_server.py` used
`monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)` to simulate "no key configured."
`pydantic-settings`' source precedence is `os.environ > .env file > field default` -- deleting
the OS env var does nothing to hide a real key sitting in the repo's own `.env` file, so
`Settings()` still read the real key straight out of `.env` and the test's "no key" assumption
was false from the start. Two sub-fixes were needed: (a) `get_settings()`'s `@lru_cache` was
not cleared in this file's autouse fixture (three other test files already did this) --
without clearing it, a *previous* test's cached `Settings` instance could leak in regardless
of env changes; added `get_settings.cache_clear()` to `_clear_lru_caches()`. (b) even with the
cache cleared, `delenv` still couldn't hide a key in `.env` -- changed to
`monkeypatch.setenv("ANTHROPIC_API_KEY", "")`, which *does* win over `.env` since `os.environ`
ranks first in pydantic-settings' precedence, and an empty string is still falsy to the
`if not settings.anthropic_api_key` check in `llm/client.py`. Reproduced both the original
failure and the fix directly in this sandbox with a temporary fake `.env` file (created, used,
then removed) before trusting it on the user's own laptop. Laptop confirmed 499/499 passed
afterward.

**Bug 2 -- six test files were checking the wrong file to decide "is the real snapshot here."**
`MANIFEST.json` (schema and column names only, no data -- see ADR-002) is always committed and
licence-safe, so it is always present, even in a bare CI checkout with no real vendor data.
`snapshot.duckdb` (the `DB_NAME` constant in `src/copilot/data/store.py`) is the actual data
file, correctly `.gitignore`d, and genuinely absent in CI. Six files had copy-pasted a
skip-if-not-built check against `MANIFEST.json` instead of `DB_NAME`, so the check always
evaluated to "snapshot exists" and these tests always ran for real in CI against an empty
DuckDB connection -- `test_golden.py`, `test_golden_v2.py`, `test_ml_forecast.py`,
`test_agent_specialists.py`, `test_orchestrator_wiring.py`, `test_snapshot.py`,
`test_store_security.py`. (`test_store_security.py`'s parametrized attack tests happened to
keep passing anyway -- most attacks fail for a security reason regardless of whether real
tables exist, and `pytest.raises(duckdb.Error)` accepts `CatalogException` too; only its one
exact-row-count assertion actually surfaced the bug.) Fixed all six to check `DB_NAME` instead.
Verified by temporarily moving the real snapshot out of `data/snapshot/`, confirming the 27
previously-crashing tests now skip cleanly ("32 passed, 27 skipped"), restoring the real
snapshot, then running the full suite again for real ("499 passed, 0 failed") to confirm the
fix broke nothing else. `ruff check`, `ruff format --check`, and `mypy` all stayed clean.

**Net effect:** all three CI jobs (`checks`'s Format check, Type check, and Tests; `image`'s
Build image) should now be green on the same push, for the first time since before 14 Oct.

## 25 Oct -- Day 9 results review: two real bugs behind the first accuracy numbers

Running `finetuning/eval_compare.py` against the Colab-trained adapter and sanity-checking a
few rows by hand (rather than trusting the summary table on sight) turned up two bugs that both
inflated or distorted the base/few-shot/QLoRA comparison -- neither is a training problem, both
are measurement/data problems.

**Bug 1 -- few-shot retrieval leaked every held-out answer to itself.** `retrieve_few_shot`
searched the *entire* `sql_pairs_v1.jsonl` for the question most similar to the one being asked,
with no exclusion for the held-out split drawn from that same file. For all 60 held-out
questions, the single most "similar" example in the file was the question itself with its own
ground-truth SQL attached (token-overlap retrieval scores an identical question 1.0), so
`base_few_shot`'s accuracy was measuring copy-paste, not generalisation -- not a fair third leg
of the base/few-shot/QLoRA comparison. **Fix:** added `few_shot_pool()` to
`finetuning/eval_compare.py`, excluding held-out rows from the retrieval pool by id *and* by
question text (belt and braces -- a re-split or hand edit could preserve one and drop the
other), wired into `main()` before any variant runs.

**Bug 2 -- vendor-name casing in `sql_pairs_v1` was not learnable from its own question.**
`generate_candidates` wrote the question in title case (`Vineyard Brands Inc`) but the SQL's
`WHERE VendorName = '...'` literal used the name's *stored* casing (`VINEYARD BRANDS INC`,
mostly upper, a few mixed) -- 314 of 327 vendor-filtered pairs. The training target held
information absent from the prompt, so the model could only guess the casing, and a wrong-case
`=` filter returns zero rows with no error -- a silent wrong answer, not an execution failure,
undercounting accuracy for reasons that have nothing to do with SQL-writing ability. **Fix:**
`src/copilot/sql/pair_generation.py` now builds every vendor filter as
`lower(VendorName) = lower('<name exactly as the question shows it>')` (`_vendor_eq`/
`_vendor_in`), and `finetuning/day9_qlora_colab.ipynb` + `eval_compare.py` both prepend a
`CASE_HINT` line to the prompt (word-for-word identical in both, enforced by
`tests/test_eval_compare.py::test_notebook_and_script_build_identical_prompts` -- train/serve
skew on this exact prompt is what Day 8's addendum work was about avoiding elsewhere).
Regenerated the dataset as `evals/datasets/sql_pairs_v2.jsonl` (`scripts/generate_sql_pairs.py`,
same seed, same 400 questions, same result rows) rather than overwriting v1, so v1 stays
available as the historical record of the pre-fix numbers. As a second, independent safety net
-- not a substitute for the real fix above -- `copilot.evals.golden.verify()`, its
`evaluators._values_match`, and `eval_compare.py`'s own row comparison now casefold string
values before comparing, so a correct answer is never marked wrong purely for differing in
letter case from the stored expectation.

Added `tests/test_eval_compare.py` (few-shot pool exclusion, notebook/script prompt parity, the
v1-vs-v2 casing rule against the committed dataset) and four new cases to
`tests/test_generate_sql_pairs.py` for the same casing rule at the generator level. Full suite:
508 passed. `ruff check`, `ruff format --check`, and `mypy` all clean.

## 25 Oct (cont.) -- a third bug, found by actually reading 3 raw generations

Re-ran `eval_compare.py` for real against the Colab-trained adapter after the two fixes above.
The printed table (`execution_accuracy` near zero for every variant, `base_few_shot` a flat
0.0) was implausible enough to not trust on sight, so before writing a single number into
`results_template.md`, printed 3 raw model outputs next to what the extraction code pulled out
of them (exactly `copilot.evals.golden`'s own "re-execute and look" standard, applied to the
measurement script itself this time) -- 2 of 3 showed the real cause immediately.

**Bug 3 -- `_extract_sql`'s fence-stripping regex ate the blank line that separated the SQL
from an instruct model's trailing explanation.** Qwen2.5-1.5B-Instruct very commonly answers
with `` ```sql ... ``` `` and then keeps talking afterward ("This query joins the
`vendor_rankings` table..."). The old extraction removed both fence markers with one greedy
`re.sub(r"^```sql\s*|^```\s*|```$", ...)`: the alternative matching the *closing* fence also
consumed the blank line right after it (`\s*` is greedy and treats newlines as whitespace), so
the SQL and the trailing prose ended up glued into one paragraph with nothing left to split
on. The result was syntactically valid SQL with an English sentence appended directly to the
end -- a guaranteed DuckDB syntax error, which is why `executable_rate` looked catastrophic
(16.7%) for reasons that had nothing to do with whether the SQL itself was any good. **Fix:**
`_extract_sql` now looks for an explicit fenced block first and takes *only* the text between
its open and close markers (`re.search(r"```(?:sql)?\s*\n(.*?)```", text, flags=re.DOTALL)`),
falling back to the old blank-line heuristic only when there's no fence at all. Verified
against the actual failing outputs before touching the real test suite. Added three cases to
`tests/test_eval_compare.py` pinning this exact failure mode (closed fence with trailing
prose, no fence at all, an unclosed fence). Full suite: 511 passed.

Separately, a real (non-bug) finding from the same 3 samples: the un-fine-tuned base model
does not reliably follow the `CASE_HINT` instruction -- one sample matched vendor names with
their title-case question spelling directly (`VendorName IN ('Ole Smoky Distillery Llc', ...)`)
instead of wrapping both sides in `lower(...)`, which returns zero rows against the real,
upper-case-stored data. Worth tracking once real numbers exist, not something to fix in the
harness.

**Still not yet done:** re-running `eval_compare.py` again with this third fix in place to get
numbers actually worth writing into `finetuning/results_template.md` and
`docs/adr/007-finetuning-outcome.md`. The adapter itself still does not need retraining -- all
three bugs found today were in the measurement script, not the training run.

## 25 Oct (cont.) -- Bug 4, the real one: the adapter never trained at all

Re-running `eval_compare.py` with Bug 3's fix in place made `base_zero_shot` and `qlora` come
back with *identical* executable and correct counts -- twice, across two separate runs. With
greedy decoding over 100+ tokens that is not a plausible coincidence, so before writing
anything down: generated the same question from the base model and from the "fine-tuned"
model side by side. The two outputs were byte-for-byte identical. Checked the adapter file
itself next (`adapter_config.json` and file sizes looked completely normal -- real target
modules, a real 74MB `adapter_model.safetensors`), then checked whether its LoRA `B` matrices
(which PEFT initializes to all-zero before any training) had actually moved: all 196 of them
were still exactly zero. The adapter was mathematically a no-op -- not "fine-tuning didn't
help," but "fine-tuning never happened."

Root cause, found by re-reading the training notebook's own `trainer.train()` output: training
loss was reported as exactly `0.000000` at every logged step. Traced to
`tokenize_example()`'s `MAX_LEN = 512`: the real prompt (schema card + question + `CASE_HINT`)
runs 650-700+ tokens on its own (confirmed: 651 tokens for one sample, 713 as the worst case
across the real 340-example training set) -- already past the 512-token cap *before the SQL
answer is even appended*. Every training example therefore lost its entire answer to
truncation, every label ended up masked to `-100` (nothing left to grade the loss on), and
`trainer.train()` ran its full 3 epochs / 66 steps computing a loss of zero the whole way,
never updating a single weight. The adapter saved at the end was still sitting at its
untrained initialization -- consistent with every earlier observation: identical outputs to
the base model, all-zero `B` matrices, a flat 0.0 training loss.

**A contributing factor, not a separate bug:** the person training this had also walked away
mid-run during an earlier attempt and the Colab runtime may have disconnected -- a real risk,
but not what actually caused this particular all-zero result; the token-truncation bug alone
is sufficient to explain it and would have produced the same zero-loss result even in one
uninterrupted sitting.

**Fix:** `MAX_LEN` raised from 512 to 1024 in `finetuning/day9_qlora_colab.ipynb`'s tokenization
cell -- comfortable headroom above the measured 713-token worst case. Requires a real
retraining run (this is the one bug today that does need the GPU step redone, not just
re-evaluation) -- not yet executed as of this entry. Once retrained: confirm the logged loss
actually decreases before trusting the adapter, then re-run `eval_compare.py` a third time for
numbers worth writing into `results_template.md` and the ADR.

## 25-26 Oct (cont.) -- retrained for real; Day 9's actual result

Retrained with `MAX_LEN=1024` in place, on Colab's T4, one uninterrupted sitting this time.
Training loss: 0.551 → 0.045 → 0.015 → 0.002 → 0.0004 → 0.0006 across the 66 logged steps -- a
real curve, not the flat `0.000000` from the broken run. Before trusting anything: the
notebook's own three sanity-check examples (end of training) matched their ground-truth SQL
**exactly, word for word**, including correctly using the `lower(...)` casing pattern -- a much
stronger signal than a summary accuracy number would have been on its own.

Re-ran `eval_compare.py` against the real adapter:

```
variant             n  executable_rate  execution_accuracy  mean_latency_s
--------------------------------------------------------------------------
base_zero_shot     60             0.25               0.017           6.764
base_few_shot      60            0.333                 0.1           3.828
qlora              60              1.0                 1.0           4.424
```

qlora clearly diverges from the base model this time (unlike the two broken runs, where it was
byte-identical) -- 1.0 execution accuracy against 0.017 and 0.1 for the un-tuned variants, and
no latency penalty either. `finetuning/results_template.md` and `docs/adr/
007-finetuning-outcome.md` filled in with these real numbers: **adopt, conditionally** -- the
one named condition being that `sql_pairs_v2`'s fixed question-template family means this
proves the model learned *that* family thoroughly, not that it generalizes to arbitrary new
question phrasings; validate against a broader set before this replaces the frontier-API call
in `TextToSqlService`'s primary path. Full suite still 511 passed; nothing in `src/` touched
by this entry.

**Net effect, four bugs total today, in order found:** few-shot retrieval leakage (measurement
bug), unlearnable vendor casing in `sql_pairs_v1` (training-data bug), an SQL-extraction
regex eating trailing model prose (measurement bug), and a `MAX_LEN=512` token cap that
silently truncated away every training example's answer (the one real training bug, requiring
an actual GPU retrain). Every one of them was found the same way -- reading a handful of raw
results by hand instead of trusting a summary table on sight -- before any number got written
down as a fact.
