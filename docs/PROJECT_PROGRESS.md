# Project Progress: Vendor Intelligence Copilot

Last updated: Tue 13 Oct 2026 (Day 2 of the 10-day sprint, sprint plan v2)

## Sprint status

| Day | Theme | Status |
|---|---|---|
| 1 | Foundations, data, golden set | Build done; repo pushed to GitHub (14 Oct). Waiting on you: AWS hardening, keys |
| 2 | Production skeleton live | Code done and tested. Waiting on you: AWS resources, domain, GitHub variables |
| 3 | LLM service, text-to-SQL, temperature and tokenization labs | Not started |
| 4 | RAG and advanced RAG | Not started |
| 5 | ML tools for the agents | Not started |
| 6 | Multi-agent system in LangGraph | Not started |
| 7 | Guardian, guardrails, approvals | Not started |
| 8 | Product, API keys, latency budget, evals in CI, release v0.1 | Not started |
| 9 | Fine-tuning benchmark and MCP (MCP never cut) | Not started |
| 10 | Package and launch the job campaign | Not started |

## Day 2 checklist

| Item | Status |
|---|---|
| FastAPI `/health` and `/version` with tests (dev and prod start-up paths) | Done |
| Multi-stage Dockerfile, non-root user, `.dockerignore` | Written; built and smoke-tested by the CI `image` job |
| Server bootstrap (`user-data.sh`), compose stack, deploy script with automatic rollback | Done, shellcheck clean |
| GitHub Actions: lint, types, tests, gitleaks, image build, gated deploy via OIDC + ECR + SSM | Done, actionlint clean |
| Prod secrets read from SSM at start-up; IAM policies for instance and deploy role | Done |
| gitleaks in pre-commit and CI; dev/prod key policy | Done |
| EC2, Elastic IP, ECR, IAM, SSM parameters created | Waiting on you |
| Domain + HTTPS on `api.vendor.<domain>` | Waiting on you |
| Landing page | Moved to Day 10 (case-study page); not on the never-cut list |

## Results

| Metric | Baseline | Current | Notes |
|---|---|---|---|
| Tests passing | 0 | 33 | `uv run pytest -q` (laptop and cloud) |
| Golden questions | 0 | 40 (27 dev, 10 test, 3 adversarial) | hash in `evals/datasets/golden_v1.manifest.json` |
| Execution accuracy, grounding, leakage rate | n/a | TBD (Day 3) | |

## Decisions

ADR-000 prompt corrections · ADR-001 separate repo (confirmed by you on 13 Oct) · ADR-002 licence-safe
snapshot · ADR-003 EC2 + Compose runtime · ADR-004 secrets in SSM, OIDC for CI.

## Costs to date

AWS $0, domain $0, LLM $0. Expected once Day 2 resources exist: about $22 per month on AWS (Mumbai).

## Live URLs

None yet. Target: `https://api.vendor.<domain>/health`.

## Next step

You: unpack and push the repo, create the AWS resources from the Day 2 guide, set the GitHub
variables, buy the domain. Me: Day 3 (LLM service, text-to-SQL, temperature and tokenization labs).
