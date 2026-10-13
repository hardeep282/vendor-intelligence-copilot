# Task runner for Windows PowerShell.  Usage:  .\tasks.ps1 <task>
# Tasks: setup | lint | typecheck | test | snapshot | check
param([Parameter(Position = 0)][string]$Task = "check")

switch ($Task) {
    "setup"     { uv sync; uv run pre-commit install }
    "lint"      { uv run ruff check .; uv run ruff format --check . }
    "typecheck" { uv run mypy }
    "test"      { uv run pytest -q }
    "snapshot"  { uv run python scripts/build_snapshot.py $args }
    "check"     { & $PSCommandPath lint; & $PSCommandPath typecheck; & $PSCommandPath test }
    default     { Write-Error "Unknown task '$Task'. See header of tasks.ps1." }
}
