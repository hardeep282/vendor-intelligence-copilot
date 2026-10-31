# HANDOFF: Vendor Intelligence Copilot, end of the 10-day sprint (Day 10) → depth track

Written: Tue 27 Oct 2026. Previous version (end of chat 7, Day 9 → Day 10) is in git history.

## Attach to the new chat

1. `AI_GenAI_Agentic_Engineer_Master_Build_Prompt_v2_7.md` (master prompt) plus Addendum A1 and
   Addendum A2 (A2 §2 is now in scope: it is the depth track's backlog)
2. `Job_Ready_Sprint_10_Days_v3.md` (for section X1, the depth-track order)
3. This file

## First message for the new chat

> DEPTH TRACK, block 1 (close-out), continuing from this handoff. The 10-day sprint is closed:
> `docs/SPRINT_REPORT.md` has the final report, the ADR-008 questions and the depth-track
> schedule. Repo `hardeep282/vendor-intelligence-copilot`, branch `main`, version 0.1.1 (tag
> `v0.1.1` pushed from my machine, or not yet -- check `git ls-remote --tags origin`). Attach
> it with push access, clone, rebuild the snapshot (`scripts/build_snapshot.py` on the public
> analytics repo's `Excel Analysis/Vendor_Summary.xlsx`, then
> `copilot.data.store.build_database()`), run `uv run pytest -q` (expect 534 passed),
> `uv run ruff check .`, `uv run mypy`, confirm state in five lines, then take the results I
> paste from the real-key scripts and fill the README's pending latency/cost rows.
> Don't re-derive decisions in `docs/adr/` (000-007) or re-explain what `docs/BUILD_LOG.md`
> covers.

## State at handoff

| Item | Value |
|---|---|
| Repo | `hardeep282/vendor-intelligence-copilot`, public since 28 Oct (history scanned clean 27 Oct) |
| Version | 0.1.1 in `pyproject.toml` and `uv.lock`; tag `v0.1.1` pushed 28 Oct (points at 584d79f) |
| Checks | 534 passed / 0 failed / 0 skipped with the snapshot built; ruff, mypy strict clean |
| Deployed | No. Target `https://api.vendor.<domain>/health` |
| Shared pages | Case study, Code Map (v9, Days 1-10), Progress Tracker -- links in `docs/PROJECT_PROGRESS.md` "Live URLs" |
| Next ADR | 008 (questions in `docs/SPRINT_REPORT.md`; you write it, per A1 §2.1) |

## Your open items (from `docs/SPRINT_REPORT.md`)

1. ~~Push tag `v0.1.1`~~ done 28 Oct.
2. ~~Make the repo public~~ done 28 Oct. Still: decide R1/R7 in writing (ADR-008), add the About text and topics, pin the repo.
3. Share the case-study page with "anyone with the link".
4. Record the demo (`docs/DEMO_SCRIPT.md`).
5. Run on your machine and paste results: `scripts/run_orchestrator_golden.py`,
   `scripts/run_eval_gate.py` (`llm_judged` layer), `scripts/run_model_selection_eval.py`,
   `scripts/run_rag_eval.py --quality`.
6. Deploy (Day 2 guide). R8: AWS Free plan ends about 25 Dec 2026.
7. Verify the Postgres checkpointer against a live Postgres (`infra/local/compose.yaml`).

## Depth-track order (schedule in `docs/SPRINT_REPORT.md`)

Close-out → evaluation and observability → Model Selection Agent to its Definition of Done →
forecasting/ML depth → advanced RAG (A2 §2.1) → LangGraph depth (A2 §2.3) → production depth
(A2 §2.2, 2.4, 2.5) → ADR-007's validation condition → remote MCP with auth → fine-tuning and
transformer-from-scratch depth.

## How this project runs (unchanged)

- Commit identity: `Hardeep Bamrah <hardeep.bamrah282@gmail.com>` with a `Co-Authored-By:`
  trailer and `Claude-Session:` line, set by repo-level `git config` in the cloud clone only.
- Claude writes and tests in the cloud workspace and pushes commits; you `git pull`. Tag pushes
  fail from the cloud session (HTTP 403) and are always yours.
- Keys never go in chat. Real-key scripts run on your machine; you paste back the printed output.
- The snapshot is rebuilt per session, never committed. `build_snapshot.py` writes Parquet;
  `build_database()` writes `snapshot.duckdb` (27 tests skip without it).
- Docs are the source of truth: `docs/BUILD_LOG.md`, `docs/PROJECT_PROGRESS.md`, `docs/adr/`.
- `docs/CODE_MAP.md` is updated in the same commit as any file add or job change. The shared Code
  Map page is now generated from it: run `uv run python scripts/build_code_map_page.py` and
  republish `docs/code-map/index.html` to the same link when it matters (not every commit).
- Public claims stay scoped: "benchmarked a QLoRA fine-tune for text-to-SQL", never "deployed a
  fine-tuned model to production" (ADR-007, R13).
