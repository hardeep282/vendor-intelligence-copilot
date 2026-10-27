# Final Daily Sprint Report — Day 10 and the 10-day sprint

Date: Tue 27 Oct 2026 · Release: `v0.1.1` (tag to be pushed from your machine, see below)

## Day 10 at a glance

| Item (sprint doc D10) | Status |
|---|---|
| README: problem, live link, architecture, agent roster, results, cost and latency, ADR index, limitations, roadmap | **Done.** Re-checked today: an overstated background line ("10+ years commercial/B2B") was replaced with an accurate one, a "no latency penalty" claim for QLoRA was corrected (it is slower than few-shot base), and two links to a `docs/decisions` folder that doesn't exist were removed |
| 3-minute demo video | **Script done** (`docs/DEMO_SCRIPT.md`). Recording is yours: it needs a local server and your API key |
| Case-study page, linked from the landing page; pin the repo | **Page published** as a shared page (interactive agent graph, results, bugs found before trusting a number). Landing page still unbuilt (needs the domain). Repo pin waits on making the repo public |
| Tag `v0.1.1` | Version bumped to 0.1.1 and pushed; **tag push is yours** (this session gets HTTP 403 on tag pushes) |
| Progress Tracker page | **Updated:** new Sprint tab (all ten days), current RAID, next steps |
| Code Map page, one-time end-of-sprint update | **Done, Version 9, Days 1–10.** Now generated from `docs/CODE_MAP.md` by `scripts/build_code_map_page.py` so it can't drift again |
| Final Daily Sprint Report | This file |
| Career half: CV variants, LinkedIn, pitch, applications | **Prepared (27 Oct), outside the repo:** 4 CV variants built from your locked master (saved to Downloads › CVs for Country and Remote based jobs › AI_Roles_Oct2026), an interview-kit page (60-second and 5-minute pitch, LinkedIn headline/About/Featured/post, 40 Tier-A questions with project-grounded answers, tough follow-ups), and a shortlist of 13 vetted live roles (CSV in the same folder). **Sending the applications is yours** |

### Found and fixed while closing out

- **`docs/CODE_MAP.md` had no Day 9 entries.** The pair generator, MCP server, fine-tuning
  notebook and comparison script shipped without them, breaking the standing same-commit rule.
  28 files were missing in total (Day 9, deploy/infra, living docs). All backfilled, plus a
  day marker on every entry.
- **The README's test count was only true with the snapshot built.** Without
  `data/snapshot/snapshot.duckdb`, 27 tests skip. Re-verified today with the snapshot rebuilt
  from the public analytics repo's workbook: **511 passed, 0 failed, 0 skipped**; ruff and
  mypy strict clean.
- **Full-history secrets scan** (gitleaks 8.24.3, 83 commits): no leaks, no data files ever
  committed, no phone number. Safe to make the repo public once you decide R1/R7.

## A1 §2.7 report fields

| Field | Today |
|---|---|
| ADR written today | **ADR-008 not yet written.** Day 10's real decision is making the repo and case study public before the system is deployed. Template and questions below; per A1 §2.1 you write the answers |
| Trade-off log rows added | None. No change today affected quality, cost or latency |
| Golden-set score | CI gate deterministic layer: PASS. `llm_judged` layer: not measured (needs your key) |
| Cost per query | One real `InsightService` call: $0.0113. Full multi-agent cost per question: not measured |
| p95 latency | Not measured end to end. Instrumented per call; needs `scripts/run_orchestrator_golden.py` with your key |

## The sprint, all ten days

| Day | Theme | Outcome |
|---|---|---|
| 1 | Foundations, data, golden set | Done. Licence-safe snapshot, 40-question golden set (46 with v2), disclosure policy (k = 5) |
| 2 | Production skeleton | Code done (API, Dockerfile, CI, deploy/rollback, OIDC). **Not provisioned**: AWS, domain, GitHub variables |
| 3 | LLM service, text-to-SQL | 8 of 9 (pair generator moved to Day 9). 6-layer validator, effort lab, tokenization lab |
| 4 | RAG | 7 of 7. recall@5 0.800, MRR 0.662. Reranker and full Ragas cut |
| 5 | ML tools | 6 of 6. Real risk classifier F1: RF 0.919, XGBoost 0.953. ETS ties naive. Model Selection Agent built |
| 6 | Multi-agent system | 7 of 7. Orchestrator + 5 specialists, Verifier, budgets, checkpointer |
| 7 | Guardian and approvals | 8 of 8. Privacy red team 23/23. Injection classifier cut |
| 8 | Product, CI gate, v0.1.0 | 7 of 7. `/ask` over SSE, auth, rate limits, CI eval gate, fallback model, trace masking |
| 9 | Fine-tuning and MCP | 6 of 6. QLoRA 1.0 vs 0.017 zero-shot (template family only). ADR-007 adopt, conditionally. MCP server |
| 10 | Package and launch | Build half done except your items below; career half in progress |

**Never-cut list, checked:** licence safety (aggregate-only snapshot, guard tests) ✓ · the
Guardian ✓ · login plus spend cap before public access ✓ (built; no public access yet) · eval
numbers ✓ · the README ✓ · trace redaction ✓ · CI eval gate ✓ · schema validation on outputs that
feed code ✓ · the MCP server ✓. Of A1's three retained drills (Corrective RAG loop, Guardian
function, graph with a conditional edge and an interrupt), the code exists for all three; whether
you've rebuilt each one yourself as a drill is for you to confirm.

**Cuts, all moved to the depth track:** cross-encoder reranker and full Ragas (Day 4), MLflow
(CSV run log instead, Day 5), LangGraph Studio (Day 6), injection classifier (Day 7), landing
page (Day 2), frontier-API row in the fine-tune comparison (Day 9).

**Costs to date:** AWS $0, domain $0. Recorded LLM spend: about $0.01 (first `InsightService`
call), $0.23 (two effort-lab runs), under $1 (Days 4–5 combined), under $1 (Day 9). Total under
$3.

**Hours used:** not tracked in the repo.

**Live URLs:** no deployed API yet. Shared pages: case study, Code Map, Progress Tracker (links in
`docs/PROJECT_PROGRESS.md`; each is private until you share it from its Share menu).

## Your items, in order

1. `git pull`, then `git tag -a v0.1.1 -m "Day 10: end of sprint"` and `git push origin v0.1.1`.
2. Decide R1 and R7 (`docs/RAID.md`), then make the repo public (GitHub → Settings → General →
   Danger Zone → Change visibility) and pin it on your profile.
3. Share the case-study page with "anyone with the link".
4. Record the demo from `docs/DEMO_SCRIPT.md`; upload unlisted; add the link to the README.
5. Run the pending real-key scripts: `run_orchestrator_golden.py`, `run_eval_gate.py`
   (`llm_judged`), `run_model_selection_eval.py`. Paste the printed results back.
6. Deploy (Day 2 guide). R8: the AWS Free plan ends about 25 Dec 2026.

## ADR-008 for you to write (A1 §2.1)

Template as in Addendum A1. Title suggestion: *Publish the repository and case study before the
system is deployed.* Questions:

1. What does a recruiter lose by seeing "runs locally" instead of a live link, and what do they
   gain from reading the code and the build log now rather than in three weeks?
2. R7 kept the repo private pending the dataset licence (R1). What is your evidence that the
   vendor names and aggregates are fine to publish, and what would make you reverse this?
3. The case study is hosted as a shared page until the domain exists. What has to be true before
   you move it, and does the link on your CV change when you do?
4. Which claims on the public pages would an interviewer most likely probe (QLoRA scope, the
   tied forecast, the pending latency numbers), and is each one stated in a way you can defend?

## Depth-track schedule (A1 §3 order + A2 §2), 3.5 h a day, Mon–Sat, from Wed 28 Oct

Estimates, not commitments. Re-plan after the first block.

| Block | Hours | Cumulative | Ends around |
|---|---|---|---|
| Close-out: real-key runs, deploy (AWS, domain, EC2), demo video | 10 | 10 | Fri 30 Oct |
| Evaluation and observability: full Ragas, judge calibration against your labels, LangSmith online | 20 | 30 | Fri 6 Nov |
| Model Selection Agent to its Definition of Done: 30 scenarios, 15 planted faults, catch rate | 35 | 65 | Wed 18 Nov |
| Forecasting and ML depth: RF vs XGBoost with proper CV, intervals, segmentation validation | 15 | 80 | Tue 24 Nov |
| Advanced RAG (A2 §2.1): cross-encoder reranker, chunking experiments, context ordering | 20 | 100 | Tue 1 Dec |
| LangGraph depth (A2 §2.3): patterns mapped in ARCHITECTURE.md, persistence, time travel, caps ADR | 12 | 112 | Sat 5 Dec |
| Production depth (A2 §2.2, 2.4, 2.5): routing, async, Locust, semantic cache, circuit breaker, OWASP red team | 30 | 142 | Wed 16 Dec |
| ADR-007's condition: validate QLoRA on non-template questions | 6 | 148 | Fri 18 Dec |
| Remote MCP with auth, FastAPI depth | 10 | 158 | Tue 22 Dec |
| Fine-tuning depth and a transformer from scratch | 30 | 188 | Fri 1 Jan 2027 |
