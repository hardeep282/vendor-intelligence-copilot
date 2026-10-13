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
