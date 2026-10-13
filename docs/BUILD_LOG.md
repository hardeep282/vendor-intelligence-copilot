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
