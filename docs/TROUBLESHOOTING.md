# Troubleshooting

Format: symptom, root cause, the commands that fixed it, how to prevent it.

## `uv sync` fails with "Readme file does not exist: README.md"

- **Cause:** `pyproject.toml` has `readme = "README.md"` and the build backend checks it exists.
- **Fix:** create `README.md` in the repo root, then run `uv sync` again.
- **Prevent:** create the README before the first sync.

## Excel sheet not found: "vw_PortfolioHealth"

- **Cause:** the sheet is named `vw_PortfolioHealth ` (trailing space).
- **Fix:** look sheets up by `str(name).strip()`; already done in `scripts/build_snapshot.py`.

## Container cannot read SSM parameters on EC2 ("Unable to locate credentials")

- **Cause:** IMDSv2 hop limit is 1, so a container (one extra network hop) cannot reach the instance metadata service.
- **Fix:** `aws ec2 modify-instance-metadata-options --instance-id <id> --http-tokens required --http-put-response-hop-limit 2`
- **Prevent:** launch with `--metadata-options HttpTokens=required,HttpPutResponseHopLimit=2` (already in the Day 2 guide).

## `run-instances` fails with "Invalid IAM Instance Profile name"

- **Cause:** a new instance profile takes a few seconds to propagate.
- **Fix:** wait 10–15 seconds and run the command again.

## Charged for an Elastic IP after stopping or terminating the instance

- **Cause:** public IPv4 addresses cost $0.005/h whether attached or idle.
- **Fix:** release it: `aws ec2 release-address --allocation-id <alloc-id>`.

## `uv` is not recognized (Windows PowerShell)

- **Cause:** uv was not installed on the laptop.
- **Fix:** `winget install --id astral-sh.uv -e`, then open a **new** PowerShell window (PATH is read at start-up) and check `uv --version`.

## `git rebase` refuses: "You have unstaged changes" with 0 lines changed

- **Cause:** the repo was created on Linux, where shell scripts carry an executable bit; Windows has no such bit, so Git
  reported a mode change on `deploy.sh` and `user-data.sh`.
- **Fix:** `git config core.fileMode false` (this repo only), then `git status --short` is empty.

## "LF will be replaced by CRLF" on shell scripts

- **Cause:** Git on Windows converts line endings; a script with CRLF fails on Linux (`/bin/bash^M: bad interpreter`).
- **Fix:** `.gitattributes` forcing `eol=lf` for `*.sh`, `*.yml`, `*.yaml`, `*.Dockerfile`; then
  `git add .gitattributes` and `git add --renormalize .` (note: `--renormalize` only touches tracked files).

## Commits show the wrong author after unpacking a package

- **Cause:** a repo-level `user.name`/`user.email` overrides your global identity.
- **Fix:** `git config --unset user.name`, `git config --unset user.email`, then (before the first push only)
  `git rebase --root --exec "git commit --amend --reset-author --no-edit"`. If a typo pauses the rebase, `git rebase --abort`.

## 27 tests skip with "snapshot not built" even after `build_snapshot.py`

**Symptom:** `uv run pytest -q` reports `484 passed, 27 skipped`, every skip reason "snapshot not
built", although `data/snapshot/*.parquet` exist.
**Cause:** those tests check for `data/snapshot/snapshot.duckdb`. `scripts/build_snapshot.py`
writes the Parquet files only; the DuckDB file is created by `copilot.data.store.build_database()`
(or lazily by `connect()` the first time the app queries).
**Fix:** `uv run python -c "from copilot.data.store import build_database; print(build_database())"`,
then rerun: 511 passed.

## CI "Build image" fails intermittently: "no space left on device"

**Symptom:** the `image` job fails at Build image with `write /app/.venv/...: no space left on
device`; some pushes pass, others fail. Tests, lint and the secrets scan all pass.
**Cause:** the image (CPU-only torch, xgboost, the spaCy model) sits right at the ~14 GB a
standard `ubuntu-24.04` runner leaves free. The 23 Oct CPU-only torch fix reduced the size but
didn't leave enough headroom.
**Fix (28 Oct):** a "Free runner disk space" step before the build in both `image` and `deploy`
deletes preinstalled toolchains the job never uses (.NET, Android SDK, Haskell, CodeQL, Boost)
and prunes Docker images, freeing well over 20 GB. `df -h /` before and after is printed in the
step log.
