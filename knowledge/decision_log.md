---
doc_type: decision_log
vendor: null
version: 1
data_class: internal
allowed_roles: [viewer, analyst, approver, admin]
---

# Decision log

Plain-language summary of the architecture decisions recorded in `docs/adr/`. For the full
context, options considered and consequences, read the linked ADR directly — this page exists so
the Knowledge agent can answer "why did we choose X" without a full ADR dump in every response.

## ADR-000: Corrections to the master prompt

The original master prompt's Section 2 facts were checked against the live repo and corrected:
XGBoost was not yet implemented (only Random Forest existed at the time); the Excel ETS 9.84%
MAPE figure is an in-sample fit, not an out-of-sample accuracy number; the real Gold view names
use `vw_` PascalCase; Power BI has 4 pages. See `docs/adr/000-corrections-to-master-prompt.md`.

## ADR-001: Repo strategy

Decision: a new, separate repo (`vendor-intelligence-copilot`) rather than building inside the
existing analytics repo. The copilot consumes a licence-safe Gold-layer snapshot and is linked
from the analytics repo's README; infrastructure code lives in `infra/` in this same repo.
Confirmed 13 Oct 2026. See `docs/adr/001-repo-strategy.md`.

## ADR-002: Licence-safe snapshot

Decision: the copilot never queries the raw licensed dataset. It queries a derived,
aggregate-only Parquet snapshot built from the analytics project's Gold views, with a licence
guard that rejects SKU-level columns and tables over a row-count threshold. The snapshot itself
is git-ignored; only its manifest is tracked, so a fresh clone must rebuild it from the source
workbook. See `docs/adr/002-licence-safe-snapshot.md`.

## ADR-003: Runtime — EC2 + Compose

Decision: an EC2 t3.small instance running a Docker Compose stack (Nginx, API, and supporting
containers) behind host-level Nginx and Certbot, in the Mumbai (ap-south-1) region. Chosen over a
managed container service for cost and because it matches the production-skills target (IAM,
SSM, Nginx, Certbot) the sprint is meant to teach. See `docs/adr/003-runtime-ec2-compose.md`.

## ADR-004: Secrets and CI auth

Decision: development API keys live in a local `.env` file (gitignored); production keys live in
AWS SSM Parameter Store as SecureString values, read by the app at start-up. CI/CD authenticates
to AWS via GitHub OIDC (no long-lived access keys), with the deploy role scoped to one ECR repo,
one instance, and the `main` branch only. See `docs/adr/004-secrets-and-ci-auth.md`.

## ADR-005: LLM provider and the temperature correction

Decision: direct Anthropic API (not Amazon Bedrock) as the LLM provider, for now — Bedrock stays
the documented upgrade path. Also recorded here: the current Anthropic model generation (Sonnet
5, Haiku 5.5, Opus 5.5) does not accept `temperature`, `top_p` or `top_k` in the Messages API; a
non-default value returns a 400 error. The nearest per-call lever is `output_config.effort`
(low/medium/high/xhigh/max), which trades reasoning depth for latency and cost rather than
output diversity at fixed sampling — so Day 3's "temperature lab" became an "effort lab" instead.
See `docs/adr/005-llm-provider.md`.

## Open decisions tracked in RAID, not yet ADRs

The public analytics repo's `Vendor_Summary.xlsx` contains SKU-level sheets from the purchased
dataset (RAID R1) — the Topmate licence needs checking before that workbook's presence in a
public repo is considered resolved. A ~0.1% revenue gap exists between the monthly-demand table
and the vendor-level views (RAID R6) — agents must not mix the two sources in one answer without
noting the discrepancy.
