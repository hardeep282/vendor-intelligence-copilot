# Code Map

What every file in this repo does, in plain language, grouped by the layer it belongs to.

**Why this file exists:** so a new chat (or a human) can answer "what does X do and why" by reading
one file instead of opening every source file and re-deriving it. **Standing rule:** whenever a new
file is added or an existing file's job changes, add/update its entry here in the same commit. This
file is maintained exactly like `docs/BUILD_LOG.md` and `docs/PROJECT_PROGRESS.md` — never let it
go stale.

Entry format per file: **what it does** · **takes in** · **gives out** · **talks to** (other files
in this repo it calls or is called by).

---

## Settings & secrets — the only places that read `.env` / AWS

### `src/copilot/settings.py`
One typed place for every config value and secret in the project.
**Takes in:** environment variables, plus a local `.env` file (never committed).
**Gives out:** a cached `Settings` object via `get_settings()`.
**Talks to:** everything else that needs a key or a path — `LLMClient`, all the `scripts/*.py`,
`copilot.data.store`. This is the *only* code that reads `.env` directly; anything that builds its
own API client (e.g. `anthropic.Anthropic()`) must go through this, or it won't see the key.

### `src/copilot/secrets.py`
Loads production secrets from AWS SSM Parameter Store when the server starts in prod.
**Takes in:** an SSM path prefix (e.g. `/vendor-copilot/prod`) and an AWS region.
**Gives out:** one environment variable per parameter (so `/vendor-copilot/prod/ANTHROPIC_API_KEY`
becomes `ANTHROPIC_API_KEY`).
**Talks to:** runs once at container start-up, before `settings.py` reads the environment.

---

## Data layer — the only way any code touches the actual numbers

### `src/copilot/data/store.py`
The only way any agent reads data. A locked-down, read-only DuckDB connection over the Parquet
snapshot — refuses file access, network access, config changes, and every write, even if a bad
query somehow got past the SQL validator.
**Takes in:** the snapshot directory (Parquet tables).
**Gives out:** a read-only DuckDB connection.
**Talks to:** `TextToSqlService`, `InsightService`, `scripts/verify_vendor_data.py` all read through
this. Layer 0 of the SQL safety design (`docs/specs/text_to_sql_safety.md`).

### `src/copilot/data/guard.py`
Makes "no raw licensed row-level data leaves the machine" a tested rule instead of a habit.
**Takes in:** a table name and its columns/row count.
**Gives out:** raises `LicenceViolation` if a table looks like row-level/SKU-level data.
**Talks to:** `scripts/build_snapshot.py` calls this before writing any Parquet table.

### `scripts/build_snapshot.py`
Turns the vendor project's Excel workbook into the aggregate-only Parquet tables the app is allowed
to query. SKU-level sheets are only ever aggregated, never copied as-is.
**Takes in:** path to `Vendor_Summary.xlsx` (local only, never committed).
**Gives out:** `data/snapshot/<table>.parquet` + `MANIFEST.json`.
**Talks to:** `guard.py` (enforces the aggregate-only rule), `store.py` (reads what this builds).

### `scripts/verify_vendor_data.py`
Prints the exact grounding data `InsightService` hands the model for one vendor, with no LLM call —
a way to fact-check a narrative by eye instead of trusting the model's own citations.
**Talks to:** calls the same `gather_vendor_data()` lookup `InsightService` uses.

---

## Guardrails — who is allowed to see what

### `src/copilot/guardrails/policy.py`
Parses `policies/disclosure.yaml` into typed objects and answers "may this role see this?".
**Takes in:** the YAML policy file.
**Gives out:** a validated `DisclosurePolicy`.
**Talks to:** `TextToSqlService` (schema linking + validator), `InsightService` (k-threshold
masking), the future Guardian agent (Day 7).

### `policies/disclosure.yaml` / `policies/sql_rules.yaml`
Data, not code: which roles may see which tables/columns (disclosure), and the structural/semantic
rules the SQL validator enforces (sql_rules). Changing a rule is a diff to these files, not Python.

---

## LLM layer — the one place every model call goes through

### `src/copilot/llm/client.py` — `LLMClient`
The one place every agent/service calls an LLM through: retries/backoff, streaming for
time-to-first-token, prompt caching, tracing (`@traceable`), per-call cost/latency/token logging.
No `temperature`/`top_p`/`top_k` — this model generation's API doesn't accept them (confirmed
against the SDK, see ADR-005); the nearest lever is `effort`.
**Takes in:** model id, system prompt, messages, optionally a Pydantic output model (`structured()`).
**Gives out:** `LLMResult` or a validated Pydantic object, paired with `CallMetrics`.
**Talks to:** `InsightService`, `TextToSqlService`, `run_effort_lab.py`, `run_tokenization_lab.py`
all call through this instead of touching the Anthropic SDK directly.

### `src/copilot/llm/prompts.py`
Versioned prompt loader — prompt text lives in reviewable YAML, not buried in Python strings. A
*behaviour* change (tone, grounding rule, output shape) is a new version file (`v2.yaml`); a pure
*capacity* fix (raising `max_tokens`) is edited in place on the existing version.
**Takes in:** a prompt name + version; `prompts/<name>/v<N>.yaml`.
**Gives out:** a validated `Prompt` with `.render_system()` / `.render_user()`.
**Talks to:** `InsightService`, `TextToSqlService` both load their prompts this way.

### `src/copilot/llm/pricing.py`
Turns a call's token counts into a USD figure — one source of truth for prices.
**Takes in:** a model ID and token counts (input/output/cache write/cache read).
**Gives out:** `cost_usd(...) -> float`.
**Talks to:** `LLMClient` (every real call), `run_tokenization_lab.py` (cost projections).

### `src/copilot/llm/types.py`
The shared result shape every LLM call returns, so logging/LangSmith/tests never branch on which
call path produced it. Holds `CallMetrics` (TTFT, latency, tokens, cost).

---

## SQL layer — turning a question into a safe query

### `src/copilot/sql/service.py` — `TextToSqlService`
One business question → one validated DuckDB query → real rows. Shows the model only its role's
tables (schema linking) and 3 similar verified examples, validates every candidate query through
all 6 validator layers before running it, and on rejection feeds the exact violations back to the
model as the next turn (self-correction, max 2 retries) rather than giving up or running bad SQL.
**Talks to:** `schema.py`, `examples.py`, `validator.py`, `store.py`, `LLMClient`.

### `src/copilot/sql/schema.py`
Builds the "schema card" shown to the model — only the tables/columns a given role may even be told
about, so the model never writes SQL for data it can't have, which would just waste a repair loop.
**Talks to:** reads from the same source-of-truth as `policy.py` and the Parquet manifest.

### `src/copilot/sql/examples.py`
Retrieves 3 golden question/SQL pairs similar to the current question, as few-shot examples —
lexical overlap, not embeddings (the golden set is small enough that a vector index would be
overkill). Examples are role-filtered so a less-privileged role is never shown a more-privileged
query shape.

### `src/copilot/sql/validator.py`
The 6-layer validator that catches two failure families before anything runs: structurally unsafe
SQL (wrong table, disguised write, catalog probe), and structurally valid SQL that would still
return a wrong *number* (a ratio column averaged across vendors, a sum after a fan-out join, two
overlapping counts added). Full trap table: `docs/specs/text_to_sql_safety.md`.
**Talks to:** `sql_rules.yaml` (the rules data), `TextToSqlService` (calls it before running SQL),
`evaluators.py`'s `leakage_free` (re-runs it as a defence-in-depth check).

---

## Evals layer — scoring the system against the golden set

### `src/copilot/evals/golden.py`
Defines what one golden question looks like and re-checks it against the snapshot.
**Gives out:** typed `GoldenQuestion` objects; `verify()` re-executes every SQL and compares results.

### `src/copilot/evals/evaluators.py`
Two separate scores per answer: `execution_accuracy` (did it compute the right numbers, or
correctly abstain) and `leakage_free` (independent re-validation of whatever SQL actually ran, so a
future service-level bug still gets caught by the eval suite). Fixed 14 Oct: row comparison used to
require an exact column-name match; now compares by *value*, in column order, per the spec.

### `src/copilot/evals/langsmith_sync.py` + `scripts/push_golden_to_langsmith.py`
Keeps one LangSmith dataset (`vendor-copilot-golden-v2`) in sync with
`evals/datasets/golden_v2.jsonl` — full replace, not incremental. The script is the thing you run on
your own machine with your `LANGSMITH_API_KEY`; it makes no LLM calls.

### `src/copilot/evals/effort_lab.py` + `scripts/run_effort_lab.py`
Sweeps `effort` (low→max) across the same golden questions and compares execution accuracy,
leakage-free rate, cost and latency at each level — the replacement for a temperature sweep, since
this model generation has no temperature. The script is what you run on your machine with your
`ANTHROPIC_API_KEY`; real money, real calls.

### `src/copilot/evals/tokenization_lab.py` + `scripts/run_tokenization_lab.py`
Compares three ways of counting tokens on this project's real prompts — Anthropic's own provider
counter (exact, a real API call), `tiktoken`, and a Hugging Face tokenizer (both local
approximations) — then projects what each would predict for cost per 1,000 requests. Real result
(14 Oct): both local tokenizers undercount badly (tiktoken -41.5%, HF -32.6%), which would make
budgeting on either one understate the real bill.

### `src/copilot/evals/__init__.py`, `src/copilot/insights/__init__.py`, `src/copilot/llm/__init__.py`
Empty package markers — no logic, just make the folder importable.

---

## Insights

### `src/copilot/insights/service.py` — `InsightService`
A grounded narrative insight for one vendor at a time — the typed, testable refactor of the legacy
analytics repo's `vendor_insights.py`. The model id lives in the prompt YAML, not hardcoded, and
every number the model may use is handed to it explicitly; nothing is looked up by the model itself.
**Takes in:** a vendor name + the caller's role.
**Gives out:** `VendorInsight` (forced structured output) + `CallMetrics`.
**Talks to:** `LLMClient`, `prompts/vendor_insight/v1.yaml`, `guard.py`'s masking rules.

---

## API

### `src/copilot/api/main.py`
The FastAPI HTTP entry point. Day 2 walking skeleton: `/health` says the process is alive,
`/version` says exactly which build is deployed. `/ask` (behind auth) comes later.

---

## Not yet started (empty package markers only, Day 4+)
`src/copilot/rag/`, `src/copilot/ml/`, `src/copilot/agents/`, `src/copilot/dl/`, `src/copilot/mcp/`,
`src/copilot/nlp/`, `src/copilot/extract/`, `src/copilot/observability/`, `src/copilot/ui/` — folders
exist with an `__init__.py` so imports work later; no real code yet.

---

## Scripts you run on your own machine (never in chat — need your real API keys)

| Script | Needs | What it does |
|---|---|---|
| `scripts/build_snapshot.py` | nothing (just the Excel file) | builds the Parquet snapshot |
| `scripts/build_golden_set.py` | the snapshot | builds `golden_v1.jsonl` |
| `scripts/verify_vendor_data.py` | the snapshot | prints raw grounding data, no LLM call |
| `scripts/push_golden_to_langsmith.py` | `LANGSMITH_API_KEY` | syncs the golden set to LangSmith |
| `scripts/run_effort_lab.py` | `ANTHROPIC_API_KEY` | real LLM calls, effort sweep |
| `scripts/run_tokenization_lab.py` | `ANTHROPIC_API_KEY` + network | real LLM calls + local tokenizer downloads |

## Tests (`tests/*.py`)
One test file per module above, named `test_<module>.py` — not documented individually here since
they mirror the module list exactly. `tests/fakes/anthropic_fakes.py` is a fake Anthropic SDK used
so `test_llm_client.py` and others can test retry/repair/caching logic without a real API key.
