# HANDOFF: Vendor Intelligence Copilot, end of chat 7 (Day 9) → start chat 8 (Day 10)

Written: Mon 26 Oct 2026. Paste this whole file into the new chat together with the two files listed under "Attach".
Superseded version (end of chat 6, Days 7-8 → start chat 7) is in git history at the previous commit to this file.

**Note on this handoff's span:** Day 9 ran across two sittings in the same chat -- steps 1 and 4
(pair generator, MCP server) on 22 Oct, then steps 2-3 and 5-6 (the fine-tuning benchmark)
scaffolded on 23 Oct and actually retrained for real on 25-26 Oct after four bugs were found and
fixed. All of it is one Day 9, covered here as a single completed day.

## Attach to the new chat (in this order)

1. `AI_GenAI_Agentic_Engineer_Master_Build_Prompt_v2_7.md` (master prompt, plus Addendum A1 --
   Model Selection Agent, guardrails/tokenization/fine-tuning/cost/latency/temperature coverage --
   and Addendum A2 §1, adopted Day 8: fallback model + graceful degradation, rate limiting,
   reliability patterns, prompt/model version pinning, determinism note)
2. `Job_Ready_Sprint_10_Days_v3.md` (sprint plan v3) -- **bring Day 10's exact step list; it was
   not re-typed into this handoff, same discipline as every prior handoff, and this new chat has
   no other way to see it**
3. This file

## First message for the new chat

> SPRINT MODE, continue from this handoff. Day 9 is fully built, tested, and decided:
> **Step 1** (question->SQL pair generator, `copilot.sql.pair_generation`): run for real on 22
> Oct, 1016 candidates, 0 execution/validator failures, sampled to 400 (`evals/datasets/
> sql_pairs_v1.jsonl`, superseded by v2 below).
> **Step 4** (Vendor Analytics MCP server, `copilot.mcp.server` -- "never cut" per the sprint's
> own cut-first list): built and run for real against the real snapshot the same session.
> **Steps 2-3 and 5-6** (QLoRA fine-tuning benchmark): scaffolded 23 Oct, then retrained for real
> 25-26 Oct on Colab's free T4 after finding and fixing four bugs -- few-shot retrieval leakage
> (held-out questions were drawing themselves as their own top example), an unlearnable
> vendor-casing pattern in `sql_pairs_v1` (fixed as `sql_pairs_v2`, 400 pairs, 85/15 split), an
> SQL-extraction bug gluing trailing model prose onto otherwise-correct SQL, and the one real
> training bug -- `MAX_LEN=512` silently truncated away every training example's SQL answer
> before it was appended, so the first "trained" adapter was a mathematical no-op (loss
> `0.000000`, every LoRA `B` matrix still zero). Fixed to `MAX_LEN=1024`, retrained in one
> uninterrupted sitting (loss 0.551 -> 0.0006 over 66 steps), sanity-checked word-for-word
> against ground truth before trusting any number. Real result: `qlora` scores 1.0 execution
> accuracy and 1.0 executable rate against `base_zero_shot` (0.017 / 0.25) and `base_few_shot`
> (0.1 / 0.333), with no latency penalty (4.424s vs 6.764s / 3.828s, n=60 held-out).
> **ADR-007: adopt, conditionally** -- `sql_pairs_v2` is a fixed template family of real
> vendor/column fill-ins, so the 1.0 proves the model learned that family thoroughly, not that it
> generalizes to arbitrary new question phrasings; validate against a broader question set before
> this replaces the frontier-API call in `TextToSqlService`'s primary path -- not yet done, the
> one open item carried forward.
> **Day 9 is 6 of 6 steps shipped.** `docs/BUILD_LOG.md` and `docs/PROJECT_PROGRESS.md` are both
> current through this point.
> Repo: hardeep282/vendor-intelligence-copilot (private), branch main, latest commit `b4b57f9`
> "Record Day 9's real result: adopt, conditionally", tag `v0.1.0` still on the Day 8 release
> commit (Day 9 added no new release tag). Attach it with push access, clone it, rebuild the
> snapshot from the public analytics repo's workbook (`scripts/build_snapshot.py`), run the
> checks (`uv run pytest -q`, `uv run ruff check .`, `uv run mypy`), confirm the state in five
> lines, flag anything inconsistent with `docs/PROJECT_PROGRESS.md`, then give me the Day 10 plan
> with hour estimates and start the build half (README first).
> Do not re-derive decisions already settled in `docs/adr/` (000-007) or re-explain things
> already covered in `docs/BUILD_LOG.md` -- read them, then build.
> Standing rule, unchanged: whenever you add a new file or change what an existing file does, add
> or update its entry in `docs/CODE_MAP.md` in the same commit. The companion Code Map HTML
> artifact (https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA, Version 8, current through Day 5)
> is due its one-time, end-of-sprint update as part of Day 10 -- this is the day that update
> finally happens, not a mid-sprint republish.
> One constraint specific to Day 10: the sprint doc says the README/case-study page can claim
> "benchmarked a QLoRA fine-tune for text-to-SQL," not "deployed a fine-tuned model to
> production" -- ADR-007 is adopt-conditionally, not adopt-and-shipped, and the copy should say
> exactly that.

## Repo and versions

| Item | Value |
|---|---|
| Repo | `hardeep282/vendor-intelligence-copilot` (private; attach with push access) |
| Branch | `main` |
| Latest commit | `b4b57f9` "Record Day 9's real result: adopt, conditionally" |
| Release tag | `v0.1.0`, still on the Day 8 release commit -- Day 9 added no new tag; Day 10 is expected to tag `v0.1.1` |
| Local folder | `C:\Projects\vendor-intelligence-copilot` |
| Analytics repo (source data) | `hardeep282/Commercial-Analytics---Beverage-Distribution-Project---Vendor-and-Stock-Analysis` (public) |
| Python / tooling | Python 3.12, uv, ruff, mypy (strict), pytest; FastAPI, boto3, anthropic, langsmith, sqlglot, tiktoken, tokenizers, sentence-transformers, chromadb, rank-bm25, langgraph 1.2.15, langgraph-checkpoint-sqlite, langgraph-checkpoint-postgres + psycopg[binary,pool], presidio-analyzer + presidio-anonymizer, scikit-learn, xgboost, shap, **peft + bitsandbytes + transformers (Day 9, Colab-only -- deliberately kept out of `pyproject.toml`, see `finetuning/README.md`)** |
| Deployed version | None yet. Target `https://api.vendor.<domain>/health` |
| Code Map artifact | https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA (Version 8, current through Day 5 -- **due its one-time end-of-sprint update during Day 10**) |
| Day 8 walkthrough artifact | https://claude.ai/artifact/LzWEFpD2k1mk1Ne8J7YZMf (commands + architecture-concept diagrams, Day 8-specific) |
| Day 10 roadmap artifact | https://claude.ai/artifact/DdsJttaoMqKyRy5QsXewEY (close-Day-9 + Day-10 task breakdown, written going into this handoff) |

## What exists (verified), end of Day 9

Everything from the Day 7-8 handoff (Guardian, approval gate, input gate, `/ask` over SSE, auth
+ rate limiting, CI eval gate, reliability/determinism, Postgres checkpointer option, minimal UI
+ `/ask/approve` -- all unchanged, still passing) **plus**, built across Day 9:

- **Question->SQL pair generator** (`copilot.sql.pair_generation`): generates candidate
  question->SQL pairs from a small template family applied to real vendor names and columns,
  executes each against the real snapshot, keeps only pairs that both run and pass the SQL
  validator. Real run: 1016 candidates -> 400 kept, 0 execution failures, 0 validator failures.
  `sql_pairs_v1.jsonl` had vendor-name literals compared case-sensitively (unlearnable -- the
  model can't learn a rule that contradicts itself across examples); `sql_pairs_v2.jsonl` fixes
  this by always matching vendor names case-insensitively, and is the dataset everything below
  actually trains and evaluates on.
- **Vendor Analytics MCP server** (`copilot.mcp.server`): exposes the project's existing vendor
  analytics as MCP tools/resources rather than bypassing `copilot.llm.client.LLMClient` or the
  five specialists -- the sprint's explicit "MCP never cut" item. Built and exercised against the
  real snapshot; `tests/test_mcp_server.py` covers it.
- **QLoRA fine-tuning benchmark** (`finetuning/`): `day9_qlora_colab.ipynb` (4-bit NF4 + LoRA
  r=16/alpha=32/dropout=0.05, completion-only loss, 3 epochs, Qwen2.5-1.5B-Instruct, Colab free
  T4) fine-tunes on `sql_pairs_v2`'s 340-pair train split; `eval_compare.py` re-executes
  base_zero_shot / base_few_shot / qlora against the 60-pair held-out split and the real
  snapshot, comparing result rows exactly (not string match). Four bugs found and fixed before
  trusting any number -- full story in `docs/BUILD_LOG.md`'s 25-26 Oct entries; the one real
  training bug (`MAX_LEN=512` truncating away every answer) required an actual GPU retrain, not
  just re-evaluation.
- **ADR-007 (fine-tuning outcome), resolved:** adopt the QLoRA-tuned model into
  `TextToSqlService`'s path, conditionally on validating against question phrasings outside
  `sql_pairs_v2`'s fixed template family first -- not yet done, and explicitly not actioned as
  part of this ADR. Also recorded as real deployment work, not done here: the adapter needs GPU
  inference hosting, which the rest of this project deliberately keeps out of (`finetuning/
  README.md` explains why GPU deps stay out of `pyproject.toml`).
- **Checks:** full suite passed with the same known-failure count as every prior day at the time
  of the last real run in this environment (511 passed per `docs/BUILD_LOG.md`'s 25-26 Oct
  entry); ruff/mypy clean. (A `uv sync`/test re-run attempted while writing this handoff hit a
  network error fetching the CPU-only `torch` wheel in this environment -- an infrastructure
  hiccup, not a code regression; re-run `uv run pytest -q` at the start of the Day 10 chat to
  confirm current numbers before building on top.)

## Canonical metrics (from the snapshot, tested) — unchanged since Day 1

Revenue $451.62M (all rows; $450.9M on the cleaned base) · total leakage $24.96M = controllable
$5.99M (loss-making $4.35M + freight $1.64M) + excise $18.97M · net profit $109.1M (24.16%) ·
126 vendors · 17 vendors = 80% of revenue · top 10 = 65.01% · health mix 10,495 SKUs (Healthy
4,112; Profitable but Slow 3,181; Loss Making 2,127; At Risk 1,048; Thin Margin 27). Golden v2
adds 5 more verified figures. Real vendor names for testing: `"DIAGEO NORTH AMERICA INC"` and
`"DIAGEO CHATEAU ESTATE WINES"`.

Day 9's own real numbers (fine-tuning benchmark, n=60 held-out each):

```
variant             n  executable_rate  execution_accuracy  mean_latency_s
--------------------------------------------------------------------------
base_zero_shot     60             0.25               0.017           6.764
base_few_shot      60            0.333                 0.1           3.828
qlora              60              1.0                 1.0           4.424
```

## Decisions (docs/adr)

ADR-000 prompt corrections · ADR-001 separate repo · ADR-002 licence-safe snapshot · ADR-003 EC2
+ Compose runtime · ADR-004 secrets in SSM, OIDC for CI · ADR-005 direct Anthropic API, not
Bedrock · ADR-006 Guardian design. **ADR-007 (new, resolved this span): fine-tuning outcome** --
adopt the QLoRA-tuned model into the production text-to-SQL path, conditionally on validating it
against question phrasings outside the benchmark's fixed template family before it replaces the
frontier-API call -- not yet actioned. No other new ADR for Day 9 -- the MCP server follows the
project's existing service-boundary conventions rather than a fresh build-vs-buy call. Next ADR
number: 008.

## Status of your actions (update before pasting)

| Action | Status |
|---|---|
| Unpack day2 package, rewrite author, push to private GitHub repo | ☑ (14 Oct) |
| AWS: Paid plan, root MFA, non-root admin, budget + anomaly alerts | ☐ |
| Server built (CloudShell), Session Manager Online | ☐ (public IP: ______) |
| CI connected: OIDC role, 5 GitHub variables, first deploy green | ☐ |
| Domain bought, `api.vendor.<domain>` A record, Certbot HTTPS | ☐ (domain: ______) |
| Dev keys in `.env`: Anthropic (spend limit set), LangSmith | ☑ |
| Prod keys in SSM: ANTHROPIC_API_KEY, LANGSMITH_API_KEY | ☐ |
| (Optional) Prod Postgres for checkpoints: a real Postgres + `CHECKPOINT_DATABASE_URL` as SSM SecureString -- omit this and the server keeps using local SQLite, fine for a single-instance deploy | ☐ |
| Verify the Postgres checkpointer against a real, live Postgres (`infra/local/compose.yaml up -d`) | ☐ |
| Run `scripts/run_orchestrator_golden.py` on your machine | ☐ |
| Run `scripts/run_eval_gate.py`'s `llm_judged` layer with a real key + snapshot + Chroma index | ☐ |
| Run `scripts/run_model_selection_eval.py` on your machine | ☐ |
| Run `scripts/build_rag_index.py` + `scripts/run_rag_eval.py` (+ `--quality`) on your machine | ☐ |
| Run `scripts/train_risk_classifier.py` against your real `vw_PortfolioHealth` export | ☑ (17 Oct) |
| A real walkthrough of the new UI against a running server (`uv run uvicorn copilot.api.main:app`) | ☐ |
| `git push` + `git push origin v0.1.0` (tag) | ☑ (22 Oct) |
| Run the QLoRA fine-tuning notebook end to end on Colab, paste the printed loss curve and sanity-check outputs back | ☑ (25-26 Oct, this chat) |
| Decide whether to pursue the Day 10 landing page + domain before or alongside the case-study page | ☐ -- flag your preference at the top of the Day 10 chat |

Day 10 can start before every unchecked row above is done -- same pattern as every day so far,
though the AWS/domain rows now matter more directly since Day 10's case-study page and demo
video are strongest with a real live link.

## How this project runs (carry forward, unchanged)

- **Commit identity:** commits made by Claude use `Hardeep Bamrah <hardeep.bamrah282@gmail.com>`
  as author with a `Co-Authored-By:` trailer (plus a `Claude-Session:` line) per that chat's own
  system reminder. Set via repo-level `git config` in the cloud clone only; never shipped to the
  laptop.
- Laptop repo has `core.fileMode=false` and `.gitattributes` (LF for scripts/config/json/jsonl).
- Claude writes and tests code in its cloud workspace and pushes to the repo; you `git pull` in
  VS Code. **Tag pushes are the one exception** -- this session's git credentials can push
  commits but not tags (`HTTP 403` on `git push origin <tag>`), confirmed twice (end of Day 8,
  and again that same chat) -- tags must be pushed from your own machine. Expect the same for
  `v0.1.1` at the end of Day 10.
- **Keys never go in chat, ever.** Real-API/network scripts run on your machine with your own
  keys; you paste back the printed results. The Day 9 fine-tuning notebook follows the same rule
  -- it runs on Colab with your own Google account, not in this cloud session, which has no GPU.
- The DuckDB snapshot is rebuilt from the public analytics repo's workbook
  (`scripts/build_snapshot.py`) -- never committed.
- **Docs are the source of truth across chats.** `docs/BUILD_LOG.md` and
  `docs/PROJECT_PROGRESS.md` are kept current after every step; read those two plus this handoff
  before building anything, and treat a decision in `docs/adr/` as settled unless you say
  otherwise.
- **Code Map:** `docs/CODE_MAP.md` updated every file add/change, same commit. The HTML artifact
  companion is a one-time, end-of-sprint update -- **Day 10 is that update**, not a mid-sprint
  republish before this.

## Open RAID items (docs/RAID.md)

R1 High: `Vendor_Summary.xlsx` licence check, still open. R2 High: scope, ongoing. R3 Medium:
only 12 months of demand. R6 Medium: 0.1% revenue gap between two source tables. R8 High: AWS
Free plan ends ~25 Dec 2026. R9 Low: Docker image only builds in CI, mitigated. R10 High:
text-to-SQL semantic traps -- layers 1-4 + golden v2 in, red team done Day 7. R11 High:
prompt-to-SQL injection -- layer 0 + sqlglot allowlist + Day 7 red team, mitigating. R12 Medium:
the Orchestrator's per-specialist timeout bounds how long it *waits*, not whether a runaway
specialist's thread actually stops -- open for a real concurrent-request deployment. **R13 New,
Medium:** the QLoRA adapter's 1.0 accuracy is proven only within `sql_pairs_v2`'s fixed question
template family (ADR-007's own condition) -- treat any claim about it in the Day 10 README/
case-study as scoped to that, not as general text-to-SQL accuracy.

## Costs to date

AWS $0, domain $0. LLM: ~$0.01 (Day 3, one real `InsightService` call). Day 4-5 real-data runs:
embedding/RAG-eval under $1 total. Day 6's `run_orchestrator_golden.py` not yet run. Day 7-8
added $0 (deterministic work, `llm_judged` layer correctly SKIPPED with no API key). Day 9 added
under $1 total: Colab's free T4 tier has no compute cost, and the real spend is the 180
base/few-shot/QLoRA generations `eval_compare.py` ran against the held-out set; the MCP server
and pair generator added $0 (deterministic / local work). Expected once Day 2 resources exist:
~$22/month on AWS (Mumbai).

## Cuts and moves (carry forward)

Landing page → Day 10, **still not built as of this handoff** -- needed before or alongside the
Day 10 case-study page, since the sprint doc has the case-study page linked from it. Day 3 step 7
→ stayed cut (built later, as Day 9 step 1). Day 4's cross-encoder reranker and full Ragas suite
→ both reduced. Day 5's MLflow → CSV run-log instead. Day 6's LangGraph Studio → cut-first. Day
7's injection *classifier* → cut-first. **Code Map HTML artifact cadence** → once at the end of
the sprint -- **that update is now due, as part of Day 10**.

## Living documents (all in the repo)

| File | Holds |
|---|---|
| `docs/PROJECT_PROGRESS.md` | Status of every day, results table, decisions, costs, next step |
| `docs/BUILD_LOG.md` | Per-day log: covered, decisions, mistakes and fixes, metrics, costs, open items |
| `docs/COMMANDS.md` | Every command used, by day, with explanations |
| `docs/TROUBLESHOOTING.md` | Problems hit and their fixes |
| `docs/RAID.md` | Risks, assumptions, issues, dependencies |
| `docs/adr/` | ADR-000 to ADR-007 |
| `docs/specs/text_to_sql_safety.md` | The 6-layer SQL safety spec Day 3 implemented |
| `docs/CODE_MAP.md` | Plain-language map of every file: what it does, takes in, gives out, talks to |
| `docs/HANDOFF.md` | This file (previous version in git history) |
| `finetuning/README.md` | How to run the Day 9 Colab notebook and comparison script |
| `finetuning/results_template.md` | Day 9's full results table, bugs found and fixed, caveats |

## Pages from earlier chats

Plan and tracker: https://claude.ai/artifact/AYJf5GTMPMdqPoXfcSztA1 · Day 1 setup guide:
https://claude.ai/artifact/LVqBF2eUBjDrB81kYF8JcC · Day 2 deploy guide:
https://claude.ai/artifact/2jkTr9nxbjB6VbBNTgLtGX · Day 3 step 4/5 explainer:
https://claude.ai/artifact/MLZ5DhA5r1wHkJNpM2D77H · Code Map (due its one-time update in Day 10):
https://claude.ai/artifact/DEhdU4uUTqPr7y1RgWDRCA · Day 8 walkthrough:
https://claude.ai/artifact/LzWEFpD2k1mk1Ne8J7YZMf · Day 10 roadmap (close-Day-9 + Day-10 task
breakdown): https://claude.ai/artifact/DdsJttaoMqKyRy5QsXewEY

## Day 10 scope — read the sprint doc for the exact step list

Known anchors going in (don't re-derive, the sprint doc v3 has the full itemized list under its
D10 heading):

1. **Theme:** "Package and launch the job campaign" -- this is the sprint's last day; the build
   half and the career half run in parallel, not sequentially.
2. **Build half (~6h):** README (problem, live link, architecture diagram, agent roster, results
   table, eval numbers, cost + latency, ADR index, limitations, roadmap); a 3-minute demo video
   (a question, agents working, a Guardian block, an approval); a case-study page on your domain
   linked from the landing page (landing page itself is still unbuilt -- see "Cuts and moves");
   tag `v0.1.1`; Progress Tracker update; final Daily Sprint Report.
3. **Career half (~5h):** CV variants (AI Analytics Consultant, GenAI Engineer, Agentic AI
   Engineer, Analytics/AI Solutions Engineer -- every line backed by the repo); LinkedIn headline/
   About/Featured + one architecture post; 60-second and 5-minute pitch, rehearsed against the
   sprint doc's 40 Tier-A interview questions; 15-20 applications across India, remote, UK
   (sponsorship) and EU.
4. **One constraint carried from ADR-007:** claim "benchmarked a QLoRA fine-tune for
   text-to-SQL," never "deployed a fine-tuned model to production" -- the README and case study
   should say exactly that.
5. **After Day 10:** the sprint doc frames this as the start of the depth track -- same repo,
   same folder layout, same agent contracts, no rewrites -- plus the deferred Addendum A2 §2
   items (reranking, chunking experiments, model routing, async/load testing, semantic caching,
   circuit breaker, full OWASP red-team set) and ADR-007's own open validation condition.

**Read `Job_Ready_Sprint_10_Days_v3.md`'s D10 section for the exact step-by-step list and hour
estimates** before planning -- this handoff deliberately doesn't re-type it, the same discipline
every prior handoff used.

## Alternative start

Your `Next_Chat_Continuation_Prompt.md` template works too: put v2.7+A1+A2§1 in Part 1, this file
in Part 2, `docs/PROJECT_PROGRESS.md` in Part 3, and "Resume at: Day 10, build half, step 1".
