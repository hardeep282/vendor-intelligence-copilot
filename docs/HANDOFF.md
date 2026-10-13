# HANDOFF: Vendor Intelligence Copilot, end of chat 1 (Days 1–2) → start chat 2 (Day 3)

Written: Tue 13 Oct 2026. Paste this whole file into the new chat together with the two files listed under "Attach".

## Attach to the new chat (in this order)

1. `AI_GenAI_Agentic_Engineer_Master_Build_Prompt_v2_3.md` (the master prompt)
2. `Job_Ready_Sprint_10_Days (1).md` (sprint plan v2: tokenization lab, temperature lab, API keys, MCP never cut)
3. This file

## First message for the new chat

> SPRINT MODE, continue from this handoff. Day 3: LLM service and text-to-SQL, as in the sprint doc v2.
> Repo: hardeep282/vendor-intelligence-copilot (private), branch main. Attach it with push access, clone it,
> rebuild the snapshot from the public analytics repo's workbook (scripts/build_snapshot.py), run the checks,
> confirm the state in five lines, flag anything inconsistent with docs/PROJECT_PROGRESS.md, then give me the
> Day 3 plan with hour estimates and start step 1.

## Repo and versions

| Item | Value |
|---|---|
| Repo | `hardeep282/vendor-intelligence-copilot` (private; you push it from the Day 2 guide, tab 1) |
| Branch | `main` |
| Commits | `feat: Day 1 foundations …` → `feat: Day 2 production skeleton - API, Docker, CI/CD, secrets` (+ this handoff commit) |
| Local folder | `C:\Projects\vendor-intelligence-copilot` (unpack `vendor-intelligence-copilot-day2.tar.gz`) |
| Analytics repo (source data) | `hardeep282/Commercial-Analytics---Beverage-Distribution-Project---Vendor-and-Stock-Analysis` (public) |
| Python / tooling | Python 3.12, uv 0.11.32, ruff 0.17.0, mypy, pytest 9; FastAPI 0.143, boto3 1.43 |
| Deployed version | None yet. Target `https://api.vendor.<domain>/health` |

## What exists (verified)

- **Data:** `scripts/build_snapshot.py` builds 11 aggregate-only Parquet tables (vendor-level views, vendor×month and
  portfolio×month demand, SKU health counts). Licence guard rejects SKU-level columns and tables over 2,000 rows.
  Parquet is git-ignored; only `data/snapshot/MANIFEST.json` is tracked. A fresh clone must rebuild it.
- **Policy:** `policies/disclosure.yaml` (public / internal / confidential / restricted; roles; k = 5) with a
  fail-closed loader in `copilot.guardrails.policy`.
- **Golden set:** `evals/datasets/golden_v1.jsonl`, 40 questions (27 dev, 10 test, 3 adversarial), every SQL answer
  produced by execution; hash in `golden_v1.manifest.json`.
- **API:** `copilot.api.main` with `/health`, `/version`; prod start-up loads secrets from SSM (`copilot.secrets`).
- **Container and server:** `docker/api.Dockerfile` (multi-stage, non-root), `infra/server/{compose.yaml,deploy.sh,user-data.sh}`.
- **CI/CD:** `.github/workflows/ci.yml`: ruff, mypy, pytest, gitleaks (full history), image build + smoke test,
  deploy on `main` via GitHub OIDC → ECR → SSM Run Command (runs only once the AWS repo variables exist).
- **IAM:** `infra/aws/*.json` (instance role reads only `/vendor-copilot/prod/*`; deploy role limited to one ECR repo,
  one instance, branch `main`).
- **Checks:** 22 tests pass; ruff, mypy, actionlint, shellcheck, gitleaks clean.

## Canonical metrics (from the snapshot, tested)

Revenue $451.62M (all rows; $450.9M on the cleaned base) · total leakage $24.96M = controllable $5.99M
(loss-making $4.35M + freight $1.64M) + excise $18.97M · net profit $109.1M (24.16%) · 126 vendors ·
17 vendors = 80% of revenue · top 10 = 65.01% · health mix 10,495 SKUs (Healthy 4,112; Profitable but Slow 3,181;
Loss Making 2,127; At Risk 1,048; Thin Margin 27).

## Decisions (docs/adr)

ADR-000 prompt corrections (no XGBoost yet; ETS 9.84% is in-sample; `vw_*` names) · ADR-001 separate repo
(confirmed 13 Oct) · ADR-002 vendor-level snapshot, never committed · ADR-003 EC2 t3.small + Compose + host
nginx/Certbot, Mumbai · ADR-004 dev keys in `.env`, prod keys in SSM, OIDC for CI, branch-scoped trust.
Next ADR number: 005 (LLM provider: Anthropic API vs Bedrock, Day 3).

## Status of your actions (update before pasting)

| Action | Status |
|---|---|
| Unpack day2 package, rewrite author, push to private GitHub repo | ☐ |
| AWS: Paid plan, root MFA, non-root admin, budget + anomaly alerts | ☐ |
| Server built (CloudShell), Session Manager Online | ☐ (public IP: ______) |
| CI connected: OIDC role, 5 GitHub variables, first deploy green | ☐ |
| Domain bought, `api.vendor.<domain>` A record, Certbot HTTPS | ☐ (domain: ______) |
| Dev keys in `.env`: Anthropic (spend limit set), LangSmith | ☐ |
| Prod keys in SSM: ANTHROPIC_API_KEY, LANGSMITH_API_KEY | ☐ |

Day 3 can start before the AWS and domain rows are done. It needs the repo on GitHub and your dev keys.

## How Day 3 runs (important)

- Claude writes and tests code in its cloud workspace and pushes to the repo; you `git pull` in VS Code.
- **Keys never go in chat.** Anything that calls the Anthropic API or LangSmith (baseline evals, temperature lab,
  token counting with the provider counter) runs on your laptop with your dev keys; you paste the printed results.
- The snapshot is rebuilt from the workbook in the public analytics repo, so evals can run anywhere.

## Open RAID items (docs/RAID.md)

R1 High: the public analytics repo contains `Vendor_Summary.xlsx` with SKU-level sheets; check the Topmate licence.
R2 High: scope. R3 Medium: only 12 months of demand. R6 Medium: monthly-demand revenue $452.06M vs vendor views
$451.62M (0.1% gap). R8 High: AWS Free plan ends about 25 Dec 2026; upgrade. R9 Low: image build only in CI.

## Costs to date

$0 spent. Expected after the server exists: about $22.35 per month in Mumbai (t3.small $16.35, IPv4 $3.65,
gp3 20 GB $1.82, Route 53 $0.50, ECR cents), plus the domain yearly.

## Cuts and moves

Landing page → Day 10 (case-study page).

## Living documents (all in the repo)

| File | Holds |
|---|---|
| `docs/PROJECT_PROGRESS.md` | Status of every day, results table, decisions, costs, next step |
| `docs/BUILD_LOG.md` | Per-day log: covered, decisions, mistakes and fixes, metrics, costs, open items |
| `docs/COMMANDS.md` | Every command used, by day, with explanations |
| `docs/TROUBLESHOOTING.md` | Problems hit and their fixes |
| `docs/RAID.md` | Risks, assumptions, issues, dependencies |
| `docs/adr/` | ADR-000 to ADR-004 |
| `docs/HANDOFF.md` | This file |

## Pages from chat 1

Plan and tracker: https://claude.ai/artifact/AYJf5GTMPMdqPoXfcSztA1 · Day 1 setup guide:
https://claude.ai/artifact/LVqBF2eUBjDrB81kYF8JcC · Day 2 deploy guide: https://claude.ai/artifact/2jkTr9nxbjB6VbBNTgLtGX

## Day 3 scope (from sprint doc v2)

LLM client wrapper (retries with backoff, timeouts, prompt caching, `@traceable`, per-call TTFT / latency / tokens /
cost logging) · prompts as versioned YAML · Pydantic outputs with forced tool call and repair retry ·
`InsightService` baseline from `vendor_insights.py` (model id becomes config; verify current IDs) · text-to-SQL with
schema linking, business rules, 3 retrieved golden examples, sqlglot allowlist, bounded self-correction ·
golden set as a LangSmith dataset with execution-accuracy and numeric-grounding evaluators · execution-verified
question→SQL pair generator (cut first → Day 9) · temperature lab (3 temperatures × 5 runs) · tokenization lab
(provider counter, tiktoken, a Hugging Face tokenizer; cost per 1,000 requests) · ADR-005 LLM provider.
