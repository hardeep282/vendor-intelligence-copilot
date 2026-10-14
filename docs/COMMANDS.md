# Commands (revision sheet)

All commands run in PowerShell from `C:\Projects\vendor-intelligence-copilot` with `uv` installed, unless noted.

## Day 1

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Create the Python environment and install pinned dependencies | `uv sync` | `uv` is the package manager; `sync` makes `.venv` match `pyproject.toml` and `uv.lock` | `.venv` folder appears; no errors |
| 2 | Install the Git pre-commit hooks | `uv run pre-commit install` | `uv run` runs a tool inside the project env; `pre-commit install` writes `.git/hooks/pre-commit` | "pre-commit installed at .git\hooks\pre-commit" |
| 3 | Format code | `uv run ruff format .` | `ruff format` rewrites files to one style; `.` means the whole repo | "N files left unchanged" or reformatted |
| 4 | Lint code | `uv run ruff check .` | `ruff check` finds bugs, import order, security smells | "All checks passed!" |
| 5 | Type-check | `uv run mypy` | `mypy` checks type hints using `[tool.mypy]` in `pyproject.toml` | "Success: no issues found" |
| 6 | Run tests | `uv run pytest -q` | `pytest` runs `tests/`; `-q` keeps output short | "17 passed" |
| 7 | Build the snapshot (needs your local workbook) | `uv run python scripts/build_snapshot.py "C:\Projects\Vendor_Performance_Analysis\Excel Analysis\Vendor_Summary.xlsx"` | Runs the builder with the workbook path as its one argument | 11 table names with row counts |
| 8 | Build the golden set | `uv run python scripts/build_golden_set.py` | Executes every golden SQL against the snapshot and writes the JSONL | JSON summary: 40 questions |
| 9 | All checks at once | `.\tasks.ps1 check` | Runs lint, typecheck and test through the task runner | All three pass |

## Day 2

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Run the API locally with auto-reload | `uv run uvicorn copilot.api.main:app --reload` | `uvicorn` serves the ASGI app `app` in module `copilot.api.main`; `--reload` restarts on code changes | "Uvicorn running on http://127.0.0.1:8000" |
| 2 | Call the health endpoint | `curl.exe http://127.0.0.1:8000/health` | `curl.exe` is the real curl on Windows (plain `curl` is a PowerShell alias) | `{"status":"ok"}` |
| 3 | Build the image locally | `docker build -f docker/api.Dockerfile --build-arg GIT_SHA=local -t copilot-api .` | `-f` picks the Dockerfile; `--build-arg` fills `ARG GIT_SHA`; `-t` names the image; `.` is the build context | "naming to docker.io/library/copilot-api" |
| 4 | Run the image | `docker run --rm -p 8000:8000 copilot-api` | `--rm` deletes the container on exit; `-p host:container` publishes the port | `/health` answers on port 8000 |
| 5 | Scan for secrets before pushing | `uv run pre-commit run gitleaks --all-files` | Runs just the gitleaks hook on every tracked file | "Detect hardcoded secrets...Passed" |

AWS commands for Day 2 are in the Day 2 guide; they run in AWS CloudShell.

## Laptop setup and first push (13–14 Oct)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Install uv | `winget install --id astral-sh.uv -e` | Windows package manager; `--id` exact package; `-e` exact match | uv installed (open a new terminal) |
| 2 | Ignore the Linux executable bit | `git config core.fileMode false` | Repo-level setting; permission changes stop counting as edits | `git status` clean |
| 3 | Remove a leftover repo-level identity | `git config --unset user.name` / `git config --unset user.email` | Deletes the repo setting so your global identity applies | No output |
| 4 | Re-author all commits (only before the first push) | `git rebase --root --exec "git commit --amend --reset-author --no-edit"` | Replays every commit and amends each with your identity | "Successfully rebased" |
| 5 | Force Linux line endings | `Set-Content -Path .gitattributes -Encoding ascii -Value "* text=auto","*.sh text eol=lf",...` | ASCII avoids PowerShell 5's BOM; one string per line | File with 5 rules |
| 6 | Apply the rules to tracked files | `git add .gitattributes` then `git add --renormalize .` | `--renormalize` re-processes tracked files only | `A  .gitattributes` |
| 7 | Connect and push | `git remote add origin https://github.com/hardeep282/vendor-intelligence-copilot.git` then `git push -u origin main` | `-u` sets the upstream for later `git push`/`git pull` | `branch 'main' set up to track 'origin/main'` |
| 8 | Get changes pushed by Claude | `git pull` | Fetches and merges `origin/main` | `Fast-forward` |

## Day 3 (step 1: LLM client wrapper)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Add Day 3 dependencies to the lockfile | `uv add anthropic langsmith sqlglot tenacity tiktoken` (done here by editing `pyproject.toml` then `uv sync --all-groups`) | Resolves and locks new packages against the pinned Python 3.12 | `uv.lock` updated, venv has the new packages |
| 2 | Rebuild the licence-safe snapshot | `uv run python scripts/build_snapshot.py "<path to Vendor_Summary.xlsx>"` | Runs the builder against the workbook; licence guard checks every table before writing Parquet | 11 table names with row counts, no `LicenceViolation` |
| 3 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order (cheapest first) | "All checks passed!" / "Success" / "47 passed" |
| 4 | Format (check only, no rewrite) | `uv run ruff format --check .` | Verifies formatting without changing files | "N files already formatted" |

No AWS, Anthropic or LangSmith key was used for any of the above -- step 1's tests run entirely
against a fake SDK (`tests/fakes/anthropic_fakes.py`). Commands that need a real `ANTHROPIC_API_KEY`
(the effort lab, the tokenization lab, the first InsightService run against the golden set) are
still to come later in Day 3 and run on your machine with your dev key, per `docs/HANDOFF.md`.

## Day 4 (steps 1-3: knowledge corpus, chunking, embeddings + Chroma store)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Rebuild the licence-safe snapshot in a fresh clone | `uv sync` then `uv run python scripts/build_snapshot.py "<path to Vendor_Summary.xlsx>"` | `uv sync` makes `.venv` match the lockfile; the builder re-derives the snapshot (never committed) | 11 table names with row counts |
| 2 | Add the embeddings and vector-store dependencies | `uv add sentence-transformers chromadb` | Resolves and locks `sentence-transformers` (local embedder), `chromadb` (vector store), and their transitive deps (torch, transformers, onnxruntime) against pinned Python 3.12 | `uv.lock` updated; `+ sentence-transformers==...`, `+ chromadb==...` in the output |
| 3 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success" / "184 passed" |
| 4 | Build the real RAG index (your machine, not this chat) | `uv run python scripts/build_rag_index.py` | Loads `knowledge/`, chunks it, downloads and runs `all-MiniLM-L6-v2` locally, upserts into `data/chroma/` | First run: N chunks embedded, 0 unchanged. Re-run after no edits: 0 embedded, N unchanged |

Steps 1-3 of Day 4 (the knowledge corpus and chunker in particular) were found already built,
tested and passing in the working tree at the start of this chat, but had never been committed --
`docs/PROJECT_PROGRESS.md` and `docs/HANDOFF.md` both said Day 4 was "Not started". Verified
against the live disclosure policy and committed as a correction rather than rebuilt or left
stranded; see `docs/BUILD_LOG.md`.

`scripts/build_rag_index.py` needs no API key (the embedding model is local and free to run), but
its first run downloads ~90MB from the Hugging Face Hub -- huggingface.co is outside this build
sandbox's proxy allowlist (same wall Day 3 hit for `tiktoken`/HF tokenizer downloads), so this one
runs on your machine, like the Day 3 effort/tokenization labs.

## Day 4 (step 4: hybrid BM25 + vector retrieval, fused with RRF)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Add the BM25 dependency | `uv add rank-bm25` | Resolves and locks `rank-bm25`, a small pure-Python Okapi BM25 implementation, against pinned Python 3.12 | `uv.lock` updated; `+ rank-bm25==0.2.2` in the output |
| 2 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success" / "196 passed" |

No API key or network access needed -- BM25 is pure lexical scoring over chunk text already in
memory, and every test uses `FakeEmbedder` for the vector half, same as steps 1-3. `rank-bm25`
ships no type stubs, so `[[tool.mypy.overrides]]` in `pyproject.toml` ignores it by name rather
than the whole-repo `ignore_missing_imports` escape hatch.

## Day 4 (step 5: permission filter inside the vector query)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success" / "208 passed" |

No new dependency -- `copilot.rag.permissions` is built entirely on Chroma's existing `where`
metadata filter (now exposed as an optional parameter on `ChunkStore.query()`) and the live
`DisclosurePolicy` already used across the rest of the repo. No API key or network access
needed; every test uses `FakeEmbedder` and `load_policy()` against the real
`policies/disclosure.yaml`.

## Day 4 (step 6: Corrective RAG loop in LangGraph)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Add the graph-orchestration dependency | `uv add langgraph` | Resolves and locks `langgraph` (the `StateGraph`/conditional-routing library used for the retrieve/grade/rewrite/generate/abstain loop) against pinned Python 3.12 | `uv.lock` updated; `+ langgraph==1.2.15` in the output |
| 2 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success" / "214 passed" |

No API key or network access needed for the tests -- every scenario in `tests/test_rag_corrective.py`
runs through `FakeMessagesResource` (same no-network convention as the rest of the repo's
LLM-calling tests) and a stub `Retriever`. Running `CorrectiveRagService.answer()` for real needs
your own `ANTHROPIC_API_KEY` plus a built Chroma index (see step 1-3's `build_rag_index.py`).

## Day 4 (step 7: RAG eval harness -- recall@5, MRR, cut-down Ragas)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success" / "233 passed" |
| 2 | Retrieval metrics only (free) | `uv run python scripts/run_rag_eval.py` | Runs recall@5 and MRR for all 20 golden questions against whatever real index already exists at `data/chroma/` -- pure arithmetic, no LLM calls | Per-question recall/RR lines, then mean recall@5 and MRR |
| 3 | A couple of questions only | `uv run python scripts/run_rag_eval.py --questions q01,q02` | Same as above, restricted to the given comma-separated golden question ids | Just those two questions' scores |
| 4 | Add quality metrics (costs money) | `uv run python scripts/run_rag_eval.py --quality` | On top of #2, runs one `CorrectiveRagService.answer()` plus two LLM-judge calls (faithfulness, context_recall) per question via your own `ANTHROPIC_API_KEY` | Per-question faithfulness/context_recall scores, then means |

No new dependency -- `recall_at_k`/`reciprocal_rank` (`copilot.evals.rag_metrics`) are pure
arithmetic, and `faithfulness`/`context_recall` (`copilot.evals.rag_quality`) are two small
structured-output LLM-judge calls through the existing `LLMClient`, not the `ragas` package (see
`docs/PROJECT_PROGRESS.md`'s "Decisions" section for why). Command #1 needs no API key or network
access -- all 4 eval modules are unit-tested against `FakeMessagesResource`/`FakeEmbedder` and the
real 20-question golden set resolved against the real corpus. Commands #2-#3 need a built index
(`scripts/build_rag_index.py`) but no API key. Command #4 needs both the built index and your own
`ANTHROPIC_API_KEY`.

## Day 5 (steps 1 & 4: forecast tool + inventory tools)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Add forecasting/inventory dependencies | `uv add statsforecast scikit-learn shap xgboost` (`scipy` already present via `statsforecast`) | Resolves and locks the Day 5 ML stack -- `statsforecast` for ETS, `scikit-learn`/`xgboost`/`shap` for the risk classifier (steps 2-3) added in the same `uv sync` so the lockfile only needs resolving once | `uv.lock` updated; `pandas` pinned down to 2.3.3 by `statsforecast`'s own constraint (was 3.0.6 -- full suite re-run after, no breakage) |
| 2 | Rebuild the snapshot (needed every fresh clone) | `uv run python scripts/build_snapshot.py "path/to/Vendor_Summary.xlsx"` | Rebuilds the 11 licence-safe Parquet tables this session's forecast/inventory numbers are computed from | 11 tables printed with row counts, matching Day 1's documented shape |
| 3 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success, no issues" / "267 passed" |
| 4 | Real forecast, right now (no API key, no network) | `uv run python -c "from copilot.ml.forecast import forecast_demand, ForecastRequest; print(forecast_demand(ForecastRequest(level='portfolio', horizon_months=3)))"` | Runs the real rolling-origin backtest and forecast against the real snapshot | portfolio WAPE 11.5% (both ETS and naive), matching the analytics repo's own "naive 11.8%" baseline |

No new "run on your machine" item from this step -- unlike every earlier day, both the forecast
tool and the inventory tools compute real, final numbers in this session, because
`portfolio_monthly_demand`/`vendor_monthly_demand` are already licence-safe aggregates (no API
key or raw SKU data needed, just the snapshot already built in step 2).

## Day 5 (steps 2-3 & 5: SKU risk classifier + CSV run-log)

| # | What this step does | Command | What each part does | Expected result |
|---|---|---|---|---|
| 1 | Run every check | `uv run ruff check . && uv run mypy && uv run pytest -q` | lint, strict type-check, tests, in that order | "All checks passed!" / "Success, no issues" / "285 passed" |
| 2 | Compare leaky vs. leakage-safe models, on synthetic data (no API key, no real SKU data) | `uv run python -c "from copilot.ml.risk_classifier import make_synthetic_skus, compare_models; df = make_synthetic_skus(n=2000, seed=42); [print(k, v.accuracy, v.f1) for k, v in compare_models(df).items()]"` | Builds the synthetic fixture and runs all 4 combinations (RF/XGBoost x leaky/safe) on one split | leaky accuracy/F1 higher than safe for both model families (RF ~0.834/0.291 -> ~0.820/0.211; XGBoost ~0.898/0.667 -> ~0.886/0.596) |
| 3 | Real run against your own `vw_PortfolioHealth` export | `uv run python scripts/train_risk_classifier.py path/to/export.csv` | Loads your real export, derives `is_at_risk` from `HealthStatus`, runs `compare_models()`, prints the leaky-vs-safe differential + top SHAP drivers, appends every result to `run_log.csv` | Real accuracy/F1 numbers to replace the synthetic ones quoted in `docs/BUILD_LOG.md`/`docs/PROJECT_PROGRESS.md` |
| 4 | Inspect the run-log | `cat run_log.csv` (or open in Excel/pandas) | Plain CSV, one row per tool call, `params`/`metrics` JSON-encoded into single cells | A row per `forecast_demand`/`compute_inventory_plan`/`classify_sku_risk` call made with `copilot.ml.run_log`'s `log_*_run()` builders |

No new dependency from this step -- `scikit-learn`/`shap`/`xgboost` were already added in the
steps-1-&-4 commit; only new `[[tool.mypy.overrides]]` entries for `shap`/`sklearn.*` (no inline
types for the pinned versions). `scripts/train_risk_classifier.py` is the "run on your machine"
item for steps 2-3, same never-in-chat convention as every other real-data script.
