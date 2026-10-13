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
