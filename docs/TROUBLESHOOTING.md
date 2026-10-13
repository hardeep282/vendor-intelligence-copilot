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
