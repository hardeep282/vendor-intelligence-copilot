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
