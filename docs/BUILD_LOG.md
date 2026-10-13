# Build Log

## 2026-10-10 · Day 1 · Foundations, data, golden set

**Covered:** repo layout and tooling; disclosure policy; licence-safe snapshot; 40-question golden set; living docs.

**Decisions:** ADR-000 (prompt corrections), ADR-001 (separate repo), ADR-002 (vendor-level snapshot, never committed).

**Mistakes and fixes:**
- `uv sync` failed because `pyproject.toml` named a `README.md` that did not exist yet. Fixed by creating a short README first.
- Excel sheet `vw_PortfolioHealth ` has a trailing space in its name. The snapshot builder strips names before lookup.
- mypy flagged `str.strip` on sheet names typed `int | str`. Fixed with `str(s)`.
- `ruff` flagged long lines in the golden-set builder and `zip` without `strict=`. Fixed by a scoped ignore and `strict=True`.

**Metrics:** 17 tests pass; snapshot totals match the canonical metrics (see PROJECT_PROGRESS.md). Revenue from the monthly-demand table is $452.06M versus $451.62M from the vendor views (RAID R6).

**Costs:** $0.

**Open:** accounts checklist (domain, AWS, LangSmith); push the repo; resolve RAID R1.
