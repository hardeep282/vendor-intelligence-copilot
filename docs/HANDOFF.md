# HANDOFF: Vendor Intelligence Copilot, end of chat 3 (Day 4) → start chat 4 (Day 5)

Written: Wed 14 Oct 2026. Paste this whole file into the new chat together with the two files listed under "Attach".
Superseded version (end of chat 2, Day 3 → start chat 3) is in git history at the previous commit to this file.

## Attach to the new chat (in this order)

1. `AI_GenAI_Agentic_Engineer_Master_Build_Prompt_v2_7.md` (master prompt, plus Addendum A1 agreed 13 Oct — Model
   Selection Agent, guardrails/tokenization/fine-tuning/cost/latency/temperature coverage)
2. `Job_Ready_Sprint_10_Days_v3.md` (sprint plan v3)
3. This file

## First message for the new chat

> SPRINT MODE, continue from this handoff. Day 4 (RAG and advanced RAG) is fully built and pushed — all 7
> steps. Day 5: ML tools for the agents, as in the sprint doc v3 (includes building XGBoost, per
> docs/adr/000-corrections-to-master-prompt.md item 1 — only the Random Forest exists so far — plus the
> Model Selection Agent from Addendum A1: LangGraph agents that pick a model for a requirement and
> scrutinize the choice via CRAG/Self-RAG-style methods, evaluated with LLM evals).
> Repo: hardeep282/vendor-intelligence-copilot (private), branch main. Attach it with push access, clone it,
> rebuild the snapshot from the public analytics repo's workbook (scripts/build_snapshot.py), run the checks
> (`uv run pytest -q`, `uv run ruff check .`, `uv run mypy`), confirm the state in five lines, flag anything
> inconsistent with docs/PROJECT_PROGRESS.md, then give me the Day 5 plan with hour estimates and start step 1.
> Do not re-derive decisions already settled in docs/adr/ or re-explain things already covered in
> docs/BUILD_LOG.md — read them, then build.
> Standing rule, every day from now on: whenever you add a new file or change what an existing file
> does, add or update its entry in docs/CODE_MAP.md in the same commit (same convention as
> BUILD_LOG.md / PROJECT_PROGRESS.md), AND update the companion Code Map HTML artifact
> (https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA, currently Version 6) the same sitting — read it first,
> add/edit entries (new files get `day: 5`, `isNew: true`, and real `talksTo` cross-references to what
> they actually call), then republish to the same URL so it never goes stale.

## Repo and versions

| Item | Value |
|---|---|
| Repo | `hardeep282/vendor-intelligence-copilot` (private; attach with push access) |
| Branch | `main` |
| Latest commit | `f8a7586` "Day 4 step 7: RAG eval harness -- recall@5, MRR, cut-down Ragas" |
| Local folder | `C:\Projects\vendor-intelligence-copilot` |
| Analytics repo (source data) | `hardeep282/Commercial-Analytics---Beverage-Distribution-Project---Vendor-and-Stock-Analysis` (public) |
| Python / tooling | Python 3.12, uv, ruff, mypy (strict), pytest; FastAPI, boto3, anthropic 1.13.0, langsmith 0.14.8, sqlglot 30.22.0, tiktoken, tokenizers, sentence-transformers, chromadb, rank-bm25, langgraph |
| Deployed version | None yet. Target `https://api.vendor.<domain>/health` |
| Code Map artifact | https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA (Version 6, current through Day 4 step 7) |

## What exists (verified), end of Day 4

Everything from the Day 1–3 handoff (data snapshot, disclosure policy, golden v1/v2, API skeleton,
Docker/CI/CD, IAM, SQL safety layer 0, LLM client, InsightService, Text-to-SQL, effort/tokenization labs —
unchanged, still all passing) **plus**, built this chat (Day 4, all 7 steps):

- **Knowledge corpus** (`copilot.rag.corpus`): 14 docs (4 methodology-family — data dictionary, metric
  definitions, decision log, methodology — + 10 clearly-labelled synthetic vendor contracts), each with
  YAML frontmatter (`doc_type`, `vendor`, `data_class`, `allowed_roles`) cross-checked against the live
  `DisclosurePolicy` so a doc's hand-authored roles can never silently drift from the real policy.
- **Heading-aware chunking** (`copilot.rag.chunking`): splits at Markdown headings, falls back to
  paragraph+overlap only past ~1000 chars; every chunk carries its doc's permission metadata plus a stable
  `chunk_id` and `content_hash`.
- **Local embeddings + Chroma store** (`copilot.rag.embeddings`, `copilot.rag.store.ChunkStore`): real
  local `all-MiniLM-L6-v2` (lazy-loaded, no download at construction) + a deterministic `FakeEmbedder` for
  every test; idempotent upserts keyed by `content_hash`, so a full rebuild skips unchanged chunks.
- **Hybrid retrieval with RRF** (`copilot.rag.retrieval.HybridRetriever`): BM25 + vector search fused via
  Reciprocal Rank Fusion (`k=60`, Cormack et al. 2009) — ranks only, no score calibration needed between
  BM25 and cosine distance. Reranker cut from this step on purpose.
- **Permission filter inside the vector query** (`copilot.rag.permissions.PermissionedRetriever`): the
  Chroma `where` filter is pushed into the ANN search itself (not applied post-hoc, which would silently
  return fewer than `n_results`); BM25's role-scoped index is built from only the visible chunks in the
  first place. Authority is always the live `DisclosurePolicy.can_view()`, never a chunk's own stored field.
- **Corrective RAG loop** (`copilot.rag.corrective.CorrectiveRagService`, LangGraph `StateGraph`):
  retrieve → grade → rewrite → retry (max 2) → abstain. No external web-search correction branch (ADR-002
  already forbids fetching outside the licence-safe corpus) — retries the same corpus with a reformulated
  query instead; a logged simplification, not a new ADR.
- **RAG eval harness** (`copilot.evals.rag_golden`, `rag_metrics`, `rag_quality`): 20-question golden set
  (`evals/datasets/rag_golden_v1.jsonl`, labelled by `doc_type`/`vendor` + a verbatim `must_contain` phrase
  so it survives re-chunking, verified to resolve to exactly 1 real chunk each), free `recall_at_k`/MRR, and
  a cut-down Ragas pair (faithfulness, context_recall — the sprint's own documented cut-first allowance)
  built as two hand-written LLM-judge calls through the existing `LLMClient` rather than adding the `ragas`
  package. CLI: `scripts/run_rag_eval.py` (`--quality` for real judge calls, costs money, off by default).
- **Checks:** 233 tests pass (`uv run pytest -q`); ruff, mypy (strict) clean across the whole repo.
- **Not yet run for real:** `scripts/build_rag_index.py` (the real embedding index) and
  `scripts/run_rag_eval.py --quality` (real faithfulness/context_recall numbers) still need your machine —
  see the status table below.

## Canonical metrics (from the snapshot, tested) — unchanged since Day 1

Revenue $451.62M (all rows; $450.9M on the cleaned base) · total leakage $24.96M = controllable $5.99M
(loss-making $4.35M + freight $1.64M) + excise $18.97M · net profit $109.1M (24.16%) · 126 vendors ·
17 vendors = 80% of revenue · top 10 = 65.01% · health mix 10,495 SKUs (Healthy 4,112; Profitable but Slow 3,181;
Loss Making 2,127; At Risk 1,048; Thin Margin 27). Golden v2 adds 5 more verified figures (total freight
$1,640,474.69; blended margin 28.72% — a ratio of sums, not `AVG(BlendedMarginPct)` = 5.31%; 2,127 loss-making +
6,334 dead-stock SKUs, never summed to 8,461).

## Decisions (docs/adr)

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot · ADR-003 EC2 + Compose
runtime · ADR-004 secrets in SSM, OIDC for CI · ADR-005 direct Anthropic API, not Bedrock (effort lab, not a
temperature lab). **No new ADR for Day 4** — the embedding model, vector store, RRF constant, Corrective RAG's
no-web-search simplification, and building the Ragas-reduced evaluators by hand all follow already-made or
already-standard choices rather than a new build-vs-buy decision; see `docs/PROJECT_PROGRESS.md`'s "Decisions"
section for the full reasoning. Next ADR number: 006 (expected Day 5, if XGBoost/model-selection involves a real
build-vs-buy call rather than just following the sprint doc).

## Status of your actions (update before pasting)

| Action | Status |
|---|---|
| Unpack day2 package, rewrite author, push to private GitHub repo | ☑ (14 Oct) |
| AWS: Paid plan, root MFA, non-root admin, budget + anomaly alerts | ☐ |
| Server built (CloudShell), Session Manager Online | ☐ (public IP: ______) |
| CI connected: OIDC role, 5 GitHub variables, first deploy green | ☐ |
| Domain bought, `api.vendor.<domain>` A record, Certbot HTTPS | ☐ (domain: ______) |
| Dev keys in `.env`: Anthropic (spend limit set), LangSmith | ☑ (used for the 14 Oct `InsightService` call) |
| Prod keys in SSM: ANTHROPIC_API_KEY, LANGSMITH_API_KEY | ☐ |
| Run `scripts/push_golden_to_langsmith.py` on your machine | ☐ |
| Run a real `TextToSqlService.answer()` call on your machine | ☐ |
| Run `scripts/run_effort_lab.py` on your machine (~$0.15–0.20) | ☐ |
| Run `scripts/run_tokenization_lab.py` on your machine | ☐ |
| Run `scripts/build_rag_index.py` on your machine (free, needs network) | ☐ |
| Run `scripts/run_rag_eval.py` on your machine (free) | ☐ |
| Run `scripts/run_rag_eval.py --quality` on your machine (small $) | ☐ |

Day 5 can start before the AWS/domain rows and the "run on your machine" rows are done — none of Day 5's likely
build steps (ML tools wrapped as agent-callable functions, XGBoost, the Model Selection Agent) need a real LLM
call by default for the parts that can be unit-tested against fakes, same pattern as every day so far. If you
did run any of the scripts above, paste the printed output into the new chat so it gets logged in
`docs/PROJECT_PROGRESS.md`.

## How this project runs (carry forward, unchanged)

- **Commit identity:** commits made by Claude use `Hardeep Bamrah <hardeep.bamrah282@gmail.com>` as author with a
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer (plus a `Claude-Session:` line — the exact
  attribution lines are given by a system reminder each chat; use whatever that chat's reminder specifies, not
  last chat's literal text). Set via repo-level `git config` in the cloud clone only; never shipped to the laptop.
- Laptop repo has `core.fileMode=false` and `.gitattributes` (LF for scripts/config/`.jsonl`/`.json`).
- Claude writes and tests code in its cloud workspace and pushes to the repo; you `git pull` in VS Code.
- **Keys never go in chat, ever.** Anything that calls the Anthropic API, LangSmith, or downloads a public
  tokenizer/embedding-model vocab runs on your machine with your own keys/network; you paste back the printed
  results. Claude builds the code and the tests (against fakes, no network) but does not run the real-call
  scripts itself.
- The DuckDB snapshot is rebuilt from the workbook in the public analytics repo (`scripts/build_snapshot.py`), so
  every check runs identically in a fresh clone or a fresh cloud session — no snapshot file is ever committed.
- **Docs are the source of truth across chats, not re-reading the whole repo from scratch.** `docs/BUILD_LOG.md`
  and `docs/PROJECT_PROGRESS.md` are kept current after every step; a new chat should read those two plus this
  handoff before building anything, and treat a decision already recorded in `docs/adr/` as settled unless you
  say otherwise.
- **Code Map, both forms, every commit that adds/changes a file:** `docs/CODE_MAP.md` (markdown, in the repo)
  and the Code Map HTML artifact (link above) must both be updated in the same sitting as the code change —
  never let either go stale a day behind the repo.

## Open RAID items (docs/RAID.md)

R1 High: the public analytics repo contains `Vendor_Summary.xlsx` with SKU-level sheets; check the Topmate
licence. R2 High: scope. R3 Medium: only 12 months of demand. R6 Medium: monthly-demand revenue $452.06M vs
vendor views $451.62M (0.1% gap). R8 High: AWS Free plan ends about 25 Dec 2026; upgrade. R9 Low: image build
only in CI. R10 High: text-to-SQL semantic traps — mitigated by the Day 3 validator + golden v2, red team
(Day 7, 8 cases) still ahead. R11 High: prompt-to-SQL injection — layer 0 + sqlglot allowlist in; still open
until Day 7's red team. **R12 New, Low:** the RAG permission filter (Day 4 step 5) is unit-tested but the
Day 7 red team should also probe it directly (e.g. a viewer asking a rephrased question to try to surface a
confidential chunk) rather than relying solely on the SQL-path red team.

## Costs to date

AWS $0, domain $0, LLM ~$0.01127 + whatever the scripts above cost when you run them (effort lab: est.
$0.15–0.20 at defaults; `run_rag_eval.py --quality`: roughly 20 questions × (1 CorrectiveRagService call + 2
judge calls) at `effort: low/medium` — expect well under $1 for the full set; the rest are a few cents or free).
Expected once Day 2 resources exist: about $22/month on AWS (Mumbai).

## Cuts and moves (carry forward)

Landing page → Day 10 (case-study page). Day 3 step 7 (question→SQL pair generator) → stayed cut; may move to
Day 9 if revisited. Day 4's cross-encoder reranker → cut from step 4, as the sprint doc itself flagged "cut
first"; `RetrievedChunk` already carries full chunk text so one slots in later as a third stage if revisited.
Day 4's Ragas suite → reduced to faithfulness + context_recall only, per the sprint doc's own cut-first
allowance for step 7.

## Living documents (all in the repo)

| File | Holds |
|---|---|
| `docs/PROJECT_PROGRESS.md` | Status of every day, results table, decisions, costs, next step |
| `docs/BUILD_LOG.md` | Per-day log: covered, decisions, mistakes and fixes, metrics, costs, open items |
| `docs/COMMANDS.md` | Every command used, by day, with explanations |
| `docs/TROUBLESHOOTING.md` | Problems hit and their fixes |
| `docs/RAID.md` | Risks, assumptions, issues, dependencies |
| `docs/adr/` | ADR-000 to ADR-005 |
| `docs/specs/text_to_sql_safety.md` | The 6-layer SQL safety spec Day 3 implemented |
| `docs/CODE_MAP.md` | Plain-language map of every file: what it does, takes in, gives out, talks to |
| `docs/HANDOFF.md` | This file (previous version in git history) |

## Pages from earlier chats

Plan and tracker: https://claude.ai/artifact/AYJf5GTMPMdqPoXfcSztA1 · Day 1 setup guide:
https://claude.ai/artifact/LVqBF2eUBjDrB81kYF8JcC · Day 2 deploy guide: https://claude.ai/artifact/2jkTr9nxbjB6VbBNTgLtGX
· Day 3 step 4/5 explainer (ruff format vs. check, validator, text-to-SQL): https://claude.ai/artifact/MLZ5DhA5r1wHkJNpM2D77H
· Code Map (every day, kept current — attach this to the new chat too): https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA

## Day 5 scope — read the sprint doc for the exact step list

Known anchors going in (don't re-derive, the sprint doc v3 has the full itemized list):

1. **XGBoost** — per `docs/adr/000-corrections-to-master-prompt.md` item 1, only the Random Forest exists in
   the analytics repo so far; XGBoost is explicitly deferred to Day 5. Likely alongside the existing K-Means
   and Random Forest as ML tools the agents can call.
2. **Model Selection Agent** (Addendum A1, agreed 13 Oct) — LangGraph agents that pick a data-science model
   for a stated requirement (e.g. K-Means for segmentation, logistic regression for classification), scrutinize
   whether the choice is correct via CRAG/Self-RAG-style methods (the Day 4 Corrective RAG loop is a direct
   precedent for the "scrutinize and retry" shape), and are evaluated with LLM evals.
3. Addendum A1 also calls out guardrails, tokenization, fine-tuning, cost control, latency, and temperature/
   effort as concerns that must stay covered through Day 5 and beyond — already true as of Day 3's effort lab
   and the guardrails layer built Day 1, worth a one-line confirmation rather than rebuilding.

**Read `Job_Ready_Sprint_10_Days_v3.md`'s Day 5 section for the exact step-by-step list and hour estimates**
before planning — this handoff deliberately doesn't re-type it to avoid it drifting out of sync with the real
sprint doc the way Day 4's "cut first" notes already did once.

## Alternative start

Your `Next_Chat_Continuation_Prompt.md` template works too: put v2.7+A1 in Part 1, this file in Part 2,
`docs/PROJECT_PROGRESS.md` in Part 3, and "Resume at: Day 5, step 1".
