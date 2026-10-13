# RAID Log

| ID | Type | Severity | Item | Response | Owner | Status |
|---|---|---|---|---|---|---|
| R1 | Risk | High | Licence: the analytics repo publicly contains `Vendor_Summary.xlsx`, with SKU-level sheets from the purchased dataset. | Read the Topmate licence. If redistribution is not allowed, remove the workbook from the repo and its history. This repo never contains data (`.gitignore` + licence guard). | Hardeep | Open |
| R2 | Risk | High | Scope: sprint plus depth track is large. | Cut-first lists per day; never cut licence safety, the Guardian, login plus spend cap, eval numbers, README. | Claude | Open |
| R3 | Assumption | Medium | Demand history is 12 months, so seasonality cannot be validated. | Forecast claims come from rolling-origin backtests only. | Claude | Open |
| R4 | Risk | Medium | AWS Free plan closes the account after 6 months or when credits run out. | Upgrade to the Paid plan; budget alerts at 50/80/100%. | Hardeep | Open |
| R5 | Issue | Low | Master prompt facts disagreed with the repo. | Fixed in ADR-000. | Claude | Closed |
| R6 | Issue | Medium | `output_monthly_demand` revenue sums to $452.06M but vendor views to $451.62M (a $0.44M, 0.1% gap between two source tables). | Agents must not mix the two sources in one answer without saying so; investigate lineage in the analytics project. | Hardeep | Open |
| R7 | Issue | Low | Public vendor names appear in the golden set and snapshot. | Kept private until R1 is resolved; vendor names are already in the public README. | Claude | Open |
| R8 | Risk | High | AWS Free plan ends about 25 Dec 2026 (76 days left on 10 Oct); the account closes unless upgraded. | Upgrade to the Paid plan before creating EC2 (Day 2 guide, step 1). | Hardeep | Open |
| R9 | Issue | Low | The Docker image cannot be built in the build workspace (registry access blocked). | CI builds and smoke-tests the image on every push; you can also build locally with Docker Desktop. | Claude | Mitigated |
| R10 | Risk | High | Valid SQL can be semantically wrong (AVG of margins 5.31% vs 28.72%; fan-out join inflates freight to $19.68M) or point outside data coverage (2025 → 0 rows). | Layers 1–4 in docs/specs/text_to_sql_safety.md on Day 3; golden v2 adds 6 trap questions. | Claude | Open |
| R11 | Risk | High | Prompt-to-SQL injection (UNION to other tables, file reads, ATTACH/COPY). | Layer 0 built: read-only DuckDB, external access off, config locked (11 attack tests). Layer 1 sqlglot allowlist on Day 3; 8 SQL red-team cases on Day 7. | Claude | Mitigating |
