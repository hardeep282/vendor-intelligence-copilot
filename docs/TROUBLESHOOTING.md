# Troubleshooting

Format: symptom, root cause, the commands that fixed it, how to prevent it.

## `uv sync` fails with "Readme file does not exist: README.md"

- **Cause:** `pyproject.toml` has `readme = "README.md"` and the build backend checks it exists.
- **Fix:** create `README.md` in the repo root, then run `uv sync` again.
- **Prevent:** create the README before the first sync.

## Excel sheet not found: "vw_PortfolioHealth"

- **Cause:** the sheet is named `vw_PortfolioHealth ` (trailing space).
- **Fix:** look sheets up by `str(name).strip()`; already done in `scripts/build_snapshot.py`.
