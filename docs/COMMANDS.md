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
