# Project Progress: Vendor Intelligence Copilot

Last updated: Sat 10 Oct 2026 (Day 1 of the 10-day sprint)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | In progress (build done; accounts pending) |
| 2 | Production skeleton live | Not started |
| 3 | LLM service and text-to-SQL | Not started |
| 4 | RAG and advanced RAG | Not started |
| 5 | ML tools for the agents | Not started |
| 6 | Multi-agent system in LangGraph | Not started |
| 7 | Guardian, guardrails, approvals | Not started |
| 8 | Product, evals in CI, release v0.1 | Not started |
| 9 | Fine-tuning benchmark and MCP | Not started |
| 10 | Package and launch the job campaign | Not started |

## Day 1 checklist

| Item | Status |
|---|---|
| Repo, `uv` env, layout, pre-commit config, settings, task runner | Done |
| Living docs skeleton, ADR-000 to ADR-002, RAID log | Done |
| Licence-safe snapshot: 11 aggregate tables in Parquet, queried with DuckDB, licence guard tested | Done |
| `policies/disclosure.yaml` with loader and tests | Done |
| 40-question golden set, every SQL answer verified by execution | Done |
| Domain bought, DNS, AWS root MFA / admin user / budgets, LangSmith key | Waiting on you |
| Repo pushed to GitHub (private until the licence question is settled) | Waiting on you |

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 0 | 17 | `uv run pytest -q` |
| Golden questions | 0 | 40 (27 dev, 10 test, 3 adversarial) | hash in `evals/datasets/golden_v1.manifest.json` |
| Execution accuracy, grounding, leakage rate | n/a | TBD (first measured on Day 3) | |

Snapshot totals match the canonical metrics: revenue $451.62M (all rows), controllable leakage $5.99M,
non-controllable $18.97M, net profit $109.1M (24.16%), 126 vendors, 17 vendors = 80% of revenue,
10,495 SKUs in the health mix.

## Decisions

See `docs/adr/`. ADR-000 corrections to the master prompt, ADR-001 repo strategy, ADR-002 snapshot granularity and Git policy.

## Costs to date

AWS $0, domain $0, LLM $0. Nothing billable has been created yet.

## Open RAID items

See `docs/RAID.md`.

## Next step

Finish the accounts checklist (domain, AWS, LangSmith), push the repo, then Day 2: FastAPI `/health`, Docker, EC2, HTTPS, CI/CD.
