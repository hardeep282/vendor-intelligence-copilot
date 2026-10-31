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

### `src/copilot/settings.py` *(day: 1)*
One typed place for every config value and secret in the project.
Day 7 step 6 added the input gate's knobs: `daily_spend_cap_usd` (already present, now actually
enforced), `rate_limit_per_minute` (default 30), `max_question_chars` (default 4000),
`kill_switch_enabled` (default `False` — the one flag an operator flips first in an incident).
Day 8, A2 §1.1 added `fallback_model` (default `None` — no fallback, so a primary-model outage
still surfaces as an error exactly as before this existed; an operational choice, left unset in
`.env.example` on purpose since ADR-005 already names the primary). Day 8 step 7 added
`checkpoint_database_url` (`SecretStr | None`, default `None` — local SQLite; a real Postgres
DSN switches `copilot.api.dependencies._build_checkpointer` to a `PostgresSaver` instead).
**Takes in:** environment variables, plus a local `.env` file (never committed).
**Gives out:** a cached `Settings` object via `get_settings()`.
**Talks to:** everything else that needs a key or a path — `LLMClient`, all the `scripts/*.py`,
`copilot.data.store`, `copilot.guardrails.input_gate` (Day 7). This is the *only* code that reads
`.env` directly; anything that builds its own API client (e.g. `anthropic.Anthropic()`) must go
through this, or it won't see the key.

### `src/copilot/secrets.py` *(day: 2)*
Loads production secrets from AWS SSM Parameter Store when the server starts in prod.
**Takes in:** an SSM path prefix (e.g. `/vendor-copilot/prod`) and an AWS region.
**Gives out:** one environment variable per parameter (so `/vendor-copilot/prod/ANTHROPIC_API_KEY`
becomes `ANTHROPIC_API_KEY`).
**Talks to:** runs once at container start-up, before `settings.py` reads the environment.

---

## Data layer — the only way any code touches the actual numbers

### `src/copilot/data/store.py` *(day: 1)*
The only way any agent reads data. A locked-down, read-only DuckDB connection over the Parquet
snapshot — refuses file access, network access, config changes, and every write, even if a bad
query somehow got past the SQL validator. The lockdown config (`enable_external_access`,
`lock_configuration`) is passed via `config=` at `connect()`-time rather than applied with `SET`
afterward (Day 8 fix — see `BUILD_LOG.md`, 22 Oct): DuckDB shares one database instance across
every connection opened to the same path within a process, so a `SET` after the 2nd-3rd
`connect()` call hit an already-locked instance and raised. `/ask` calls `connect()` once per
request, which made this a production blocker, not just a test flake.
**Takes in:** the snapshot directory (Parquet tables).
**Gives out:** a read-only DuckDB connection, safe to open repeatedly in one long-lived process.
**Talks to:** `TextToSqlService`, `InsightService`, `scripts/verify_vendor_data.py` all read through
this. Layer 0 of the SQL safety design (`docs/specs/text_to_sql_safety.md`).

### `src/copilot/data/guard.py` *(day: 1)*
Makes "no raw licensed row-level data leaves the machine" a tested rule instead of a habit.
**Takes in:** a table name and its columns/row count.
**Gives out:** raises `LicenceViolation` if a table looks like row-level/SKU-level data.
**Talks to:** `scripts/build_snapshot.py` calls this before writing any Parquet table.


### `src/copilot/data/units.py` -- `describe_units()` *(day: 10, isNew: true)*
Added 30 Oct 2026, after the sprint. What each snapshot column measures: "US dollars", "units
sold, not dollars", "percent of that vendor's total revenue", and so on. Every percentage label
was checked by recomputing it from the snapshot. `describe_units(sql)` labels each selected
column that reads exactly one known column (directly or via SUM/AVG/MIN/MAX/ROUND); ratios,
COUNTs and unknown columns get no label rather than a guessed one.
**Takes in:** the SQL a Data Analyst query ran.
**Gives out:** one plain-English units line per labelled output column.
**Talks to:** `run_data_analyst` appends the lines to its findings as "Units: ...", which the
v2 draft and verify prompts use.

**Also (30 Oct):** `describe_ordering(sql)` names the measure the rows are sorted by (an ORDER BY alias is mapped back to its source column), so the Verifier can compare a ranking with the question.

### `scripts/build_snapshot.py` *(day: 1)*
Turns the vendor project's Excel workbook into the aggregate-only Parquet tables the app is allowed
to query. SKU-level sheets are only ever aggregated, never copied as-is.
**Takes in:** path to `Vendor_Summary.xlsx` (local only, never committed).
**Gives out:** `data/snapshot/<table>.parquet` + `MANIFEST.json`.
**Talks to:** `guard.py` (enforces the aggregate-only rule), `store.py` (reads what this builds).

### `scripts/verify_vendor_data.py` *(day: 1)*
Prints the exact grounding data `InsightService` hands the model for one vendor, with no LLM call —
a way to fact-check a narrative by eye instead of trusting the model's own citations.
**Talks to:** calls the same `gather_vendor_data()` lookup `InsightService` uses.

---

## Guardrails — who is allowed to see what

### `src/copilot/guardrails/guardian.py` -- `Guardian` *(day: 7, isNew: true)*
Master prompt C4's single mandatory final pass. `Guardian.review(result)` runs 8 checks,
cheapest-first, against anything shaped like an `OrchestratorResult` (a `_Reviewable` Protocol --
`role`/`answer`/`results`/`verified` -- not an import of that class, to avoid a circular import
with `orchestrator.py`): `_check_canary` (the agent-specific `CANARY-<AGENT>` markers every
system prompt now carries, via `canary.py`, leaking into output = BLOCK), `_check_restricted_
names` (any `policies/disclosure.yaml` `restricted_names` table/view named in the answer =
BLOCK), `_check_raw_row_shape` (`RAW_ROW_PATTERN`: 10+ consecutive pipe/tab-delimited 3+-field
lines = BLOCK -- a real row-level export, not an illustrative summary table), `_check_role_
policy` (any `AgentResult.data_classes` the requesting role's `DisclosurePolicy.can_view` says no
to = BLOCK), `_check_vendor_audience` (an Action draft present + any *other* specialist's data
classes beyond `vendor_facing_audience.allowed_classes` = BLOCK), `_check_secrets` (`_SECRET_
PATTERNS`: Anthropic/AWS/bearer-token shapes = BLOCK), `_check_pii` (`pii.find_pii` hits =
REDACT, one finding per entity), `_check_grounding` (`not result.verified` = ESCALATE, not
BLOCK -- unconfirmed-safe isn't known-unsafe). The worst-severity finding (`block` > `escalate` >
`redact` > `allow`) decides `outcome`; every finding's `code` lands in `reason_codes` regardless
of which one won, so the audit log shows everything that fired. `safe_answer` is the real text on
ALLOW, a copy with each PII span replaced by `[REDACTED:<TYPE>]` on REDACT, or one of two fixed
generic messages (naming the reason codes, nothing else) on BLOCK/ESCALATE.
**Takes in:** a `_Reviewable` (role, answer, specialist results, verified flag) + an optional
`DisclosurePolicy` (defaults to `load_policy()`).
**Gives out:** `GuardianVerdict` (`outcome`, `reason_codes`, `findings`, `safe_answer`,
`policy_version`); `Finding`; `GuardianOutcome`; `RAW_ROW_PATTERN`.
**Talks to:** `copilot.agents.contracts` (`AgentResult`); `copilot.guardrails.pii` (`find_pii`);
`copilot.guardrails.policy` (`DataClass`/`DisclosurePolicy`/`Role`/`load_policy`). Called from
`copilot.agents.orchestrator._guardian_node`/`_approval_gate` -- the only node between `finalize`
and `END` (step 4's topology test, `tests/test_orchestrator.py::
test_every_path_to_end_passes_through_guardian`), and the re-review every approver `edit` gets
(step 5) before its text is accepted.

### `src/copilot/guardrails/pii.py` -- `find_pii()` *(day: 7, isNew: true)*
PII detection for `Guardian._check_pii`/`_apply_redactions`. Presidio (`AnalyzerEngine` + the
`en_core_web_lg` spaCy model) when it's installed and the model loads; a dependency-free regex
fallback (`EMAIL_ADDRESS`/`PHONE_NUMBER`/`CREDIT_CARD`) otherwise, so the check never silently
no-ops just because a model wasn't available in some environment. `_get_analyzer()` builds and
caches the `AnalyzerEngine` at module level (construction, not `.analyze()`, is the slow part --
an uncached version made the test suite hang); a failed build is cached too, so a missing model
doesn't re-attempt on every call. `find_pii` tries Presidio first via `_get_analyzer()`, falls
back to regex only when Presidio itself returns `None` (not installed, model missing, or an
analysis-time failure) -- never both, so a caller can tell from `PiiEntity.source` which layer
actually ran. Tests (`tests/test_guardrails_pii.py`) assert against `_regex_entities` directly,
since Presidio's availability varies by environment; `Guardian`'s own tests exercise `find_pii`
itself, whichever backend fires.
**Takes in:** a string (an answer about to be shown to a user).
**Gives out:** `list[PiiEntity]` (`entity_type`, `text`, `source: "presidio" | "regex_fallback"`).
**Talks to:** `copilot.guardrails.guardian` is the only caller.

**30 Oct 2026:** Presidio now runs only `PRESIDIO_ENTITIES` (email, phone, card, IBAN, US SSN, UK NHS) above `PRESIDIO_SCORE_THRESHOLD` 0.4. With every recognizer on, a real forecast answer was flagged as DATE_TIME, URL and US_DRIVER_LICENSE. PERSON is excluded because vendor names look like personal names.

### `src/copilot/guardrails/canary.py` -- `canary_token()`/`canary_line()` *(day: 7, isNew: true)*
Fixed per-agent markers planted in every system prompt this project builds, so any appearance of
one in a *final answer* is unambiguous proof of a system-prompt/instruction leak, not a guess.
`canary_token(agent)` -> `f"{policy.canary.prefix}{agent.upper()}"` (prefix from `policies/
disclosure.yaml`'s `canary.prefix`, currently `"CANARY-"`); `canary_line(agent)` wraps that into
one appendable instruction line. Appended to every system prompt that reaches an LLM in this
project: `TextToSqlService.answer()` (`"data_analyst"`), `run_action()` (`"action"`),
`CorrectiveRagService._grade`/`_rewrite`/`_generate` (`"knowledge_grade"`/`"knowledge_rewrite"`/
`"knowledge_generate"`), and `Orchestrator._plan`/`_draft`/`_verify`
(`"orchestrator_plan"`/`"orchestrator_draft"`/`"orchestrator_verify"`) -- one token per call site,
not per agent, since a leak at the draft step versus the verify step says something different
about where it came from.
**Takes in:** an agent/call-site name (any string -- not restricted to `AgentName`, since
`orchestrator_plan`/`orchestrator_draft`/`orchestrator_verify`/`knowledge_grade`/etc. aren't
specialist names).
**Gives out:** `canary_token(agent) -> str`, `canary_line(agent) -> str`.
**Talks to:** `copilot.guardrails.policy` (`load_policy`, cached at module level);
`copilot.guardrails.guardian._check_canary` is the only check that looks for these tokens.

### `src/copilot/guardrails/audit_log.py` -- `log_decision()`/`log_approval()` *(day: 7, isNew: true)*
A durable, append-only JSONL record of every Guardian decision and every approver decision --
independent of LangSmith on purpose (traces can be sampled/redacted/rotated, step 7; this file is
the compliance-grade record that has to survive that). `log_decision(verdict, question=, role=)`
writes one `"event": "guardian_decision"` row per `GuardianVerdict`; `log_approval(question=,
role=, decision=, final_answer=)` writes one `"event": "approval_decision"` row per approve/edit/
reject call (no `GuardianVerdict` to log there -- an edit gets its own separate `log_decision`
row from the re-review). Both never raise into the caller: a write wrapped in `try/except OSError`
returns `True`/`False` instead, because an audit-log write problem must not itself block an
already-decided answer from reaching the user. `read_decisions(path)` returns `[]` for a log that
doesn't exist yet. Local-only, never committed (`data/audit/*.jsonl` added to `.gitignore`
alongside this file -- no existing wildcard covered `.jsonl`). Day 8: `log_decision` takes an
optional `review_id=` (a uuid4 string the orchestrator generates only for an ESCALATE outcome),
written into the row so a future reviewer can join a `pending_review` status back to its exact
audit-log entry -- `None`/absent for every other outcome.
**Takes in:** a `GuardianVerdict` + question/role + optional `review_id` (`log_decision`), or
question/role/decision/final_answer (`log_approval`).
**Gives out:** `True`/`False` per write; `list[dict]` from `read_decisions`.
**Talks to:** `copilot.guardrails.guardian` (`GuardianVerdict`); `copilot.settings`
(`REPO_ROOT`). Called from `copilot.agents.orchestrator._guardian_node` and `_approval_gate`.

### `src/copilot/guardrails/input_gate.py` -- `InputGate` *(day: 7, isNew: true)*
Master prompt D2/C4's input half of defence in depth (the Guardian above is the output half) --
checks that run on the raw question *before* the Orchestrator's `plan` node, so a bad request
never spends an LLM call. `InputGate.review(question, role)` runs 6 checks, cheapest first:
`_check_kill_switch` (one flag, `Settings.kill_switch_enabled`), `_check_length` (`len()` against
`Settings.max_question_chars`, default 4000), `_check_injection` (`_INJECTION_PATTERNS`: blunt,
common phrasings -- "ignore previous instructions", "reveal your system prompt", "you are now",
etc. -- the sprint doc's one Day 7 cut-first item is the *classifier*; least-privilege tools
downstream, not these regexes alone, are the real backstop against a cleverly-worded injection
that slips past them), `_check_scope` (`_OFF_TOPIC_PATTERNS`: a small set of clearly-not-vendor-
procurement request shapes -- "write me a poem", "tell me a joke" -- false negatives here are
the Orchestrator's/Guardian's problem; false positives on a real question would be worse),
`_check_rate_limit` (`RateLimiter`, an in-memory per-role sliding window, `Settings.
rate_limit_per_minute`, default 30/min -- process-local by design, resets on restart),
`_check_spend_cap` (`SpendTracker`, a role's cumulative spend *today* read from a small JSON
file, `Settings.daily_spend_cap_usd`, default $5 -- has to survive a restart within the same day,
unlike the rate limiter, so this one does touch disk). Every finding is `outcome="block"` (no
redact/escalate on the input side -- see the module docstring for why); any finding at all means
the verdict blocks, with every firing code in `reason_codes`. `InputGate.record_spend(role,
cost_usd)` is the other half of the spend cap: called by the Orchestrator *after* a run finishes
with its real `total_cost_usd` (the gate itself, running before the request's own cost exists,
can only ever check *past* spend). `RateLimiter`/`SpendTracker` are injectable (same construction
pattern as `Guardian`), so tests can isolate or fast-forward either one without touching real
settings or `data/spend/` -- `tests/conftest.py`'s autouse `_isolated_spend_log` fixture does
exactly that for every Orchestrator test that doesn't build its own `InputGate` explicitly.
**Takes in:** a question string + a `Role`; optional `RateLimiter`/`SpendTracker`/limit overrides
at construction (defaults come from `copilot.settings.get_settings()`).
**Gives out:** `GateVerdict` (`outcome`, `reason_codes`, `findings`, `message`); `Finding`;
`GateOutcome`; `RateLimiter`; `SpendTracker`; `DEFAULT_SPEND_LOG_PATH`.
**Talks to:** `copilot.guardrails.policy` (`Role`); `copilot.settings` (`REPO_ROOT`,
`get_settings`). Called from `copilot.agents.orchestrator.Orchestrator.answer` -- the first thing
that runs, before `plan` -- and `.record_spend` once the run (or an input-gate pass-through) has
finished.

### `src/copilot/guardrails/secret_patterns.py` *(day: 7, isNew: true)*
A leaf module (no project imports) holding just `SECRET_PATTERNS` -- split out of `guardian.py`
so `trace_masking.py` (below) can reuse the exact same regexes without creating an import cycle
(`guardian.py` imports `copilot.agents.contracts` for `AgentResult`'s type hint, which imports
`copilot.llm.client` for `Effort` -- and `llm/client.py` is exactly the module that needs to
import the masking function, so `trace_masking -> guardian -> contracts -> llm.client` would
have closed the loop; confirmed by actually hitting the `ImportError` before this was split out).
**Gives out:** `SECRET_PATTERNS` (anthropic_api_key/aws_access_key_id/aws_secret_access_key/
generic_bearer_token regexes).
**Talks to:** `copilot.guardrails.guardian` (`_check_secrets`) and `copilot.guardrails.
trace_masking` both import from here; neither imports the other.

### `src/copilot/guardrails/trace_masking.py` -- `mask_run_payload()` *(day: 7, isNew: true)*
Day 7 step 7 (sprint doc: "anonymizer rules, hidden restricted payloads"). Masks what actually
gets *recorded* in a LangSmith trace -- independent of the Guardian, which only ever sees the
Orchestrator's one final answer; an intermediate specialist prompt can reference a Restricted
table by name on its way to a correctly-redacted final answer, and that intermediate payload
needs its own masking before anything reaches LangSmith's servers. `mask_run_payload(payload)`:
if any `policies/disclosure.yaml` `restricted_names` table/view appears anywhere in the payload
(recursively, through nested dicts/lists), the *entire* payload is replaced with one marker
(`RESTRICTED_PAYLOAD_MARKER`) -- "hidden restricted payloads" means the whole thing, not
selective redaction, since a payload that already names a Restricted source is already out of
bounds for what this project's licence/disclosure rules say should sit in a third-party trace
store. Otherwise, every string value (recursively) gets PII (`copilot.guardrails.pii.find_pii`)
and secret (`SECRET_PATTERNS`) matches replaced with `[REDACTED:<TYPE>]` -- same redaction shape
`Guardian._apply_redactions` uses on the output side, applied here to inputs *and* outputs.
**Why wired as `@traceable(process_inputs=mask_run_payload, process_outputs=mask_run_payload)`
on `LLMClient.complete`/`.structured` themselves, not a `langsmith.Client(anonymizer=...)`
threaded through every call site:** two things ruled that out, both confirmed with throwaway
scripts before choosing this: constructing a `Client()` eagerly calls `GET /info` over the
network (bad to do at import/decoration time just to attach an anonymizer); and setting a masked
client as langsmith's own default via its `contextvars`-based context doesn't survive crossing
into `_run_specialist`'s `ThreadPoolExecutor` worker thread (a `ContextVar.set()` in the main
thread is invisible there -- confirmed empirically). A plain function reference baked into the
decorator at the one choke point every LLM call already goes through sidesteps both problems
with no change needed at any of this project's other call sites. Only what's *recorded* for the
trace is masked -- the real return value `complete`/`structured` hand back to their caller is
never touched.
**Takes in:** the `inputs`/`outputs` dict `@traceable` builds for one LLM call.
**Gives out:** `mask_run_payload(payload) -> dict`; `RESTRICTED_PAYLOAD_MARKER`.
**Talks to:** `copilot.guardrails.pii` (`find_pii`); `copilot.guardrails.policy`
(`load_policy`, cached at module level); `copilot.guardrails.secret_patterns`
(`SECRET_PATTERNS`). Called from `copilot.llm.client.LLMClient.complete`/`.structured`'s
`@traceable` decorators -- the only caller.

**31 Oct 2026:** `mask_run_payload` accepts non-dict outputs (LangSmith passes tuples straight through) and masks inside pydantic models via `model_dump()`.

### `src/copilot/guardrails/policy.py` *(day: 1)*
Parses `policies/disclosure.yaml` into typed objects and answers "may this role see this?".
**Takes in:** the YAML policy file.
**Gives out:** a validated `DisclosurePolicy`.
**Talks to:** `TextToSqlService` (schema linking + validator), `InsightService` (k-threshold
masking), `copilot.guardrails.guardian`/`canary` (Day 7: role-policy/vendor-audience checks and
the canary-token prefix both read this same policy object).

### `policies/disclosure.yaml` / `policies/sql_rules.yaml` *(day: 1)*
Data, not code: which roles may see which tables/columns (disclosure), and the structural/semantic
rules the SQL validator enforces (sql_rules). Changing a rule is a diff to these files, not Python.

---

## LLM layer — the one place every model call goes through

### `src/copilot/llm/client.py` — `LLMClient` *(day: 3)*
The one place every agent/service calls an LLM through: retries/backoff, streaming for
time-to-first-token, prompt caching, tracing (`@traceable`), per-call cost/latency/token logging.
No `temperature`/`top_p`/`top_k` — this model generation's API doesn't accept them (confirmed
against the SDK, see ADR-005); the nearest lever is `effort`. Day 7 step 7: `complete`/
`structured`'s `@traceable` decorators now also carry `process_inputs=mask_run_payload,
process_outputs=mask_run_payload` (`copilot.guardrails.trace_masking`) — every LLM call's
recorded trace is masked (PII/secrets redacted, a Restricted-table mention hides the whole
payload) before anything reaches LangSmith, with no change needed at any call site elsewhere
in the codebase. See that module's own entry for why a plain function here, not a
`Client(anonymizer=...)`, was the right call.
Day 8, Addendum A2 §1.1 "reliability layer": a new `_with_fallback()` wraps every `complete()`/
`structured()` call — if the primary model's own `_retrying()` budget (4 attempts) is fully
exhausted on a retryable error, and a different `fallback_model` is configured (constructor arg,
default reads `Settings.fallback_model`; `None` means no fallback, today's default), one more
attempt runs against the fallback with its own fresh retry budget (and, for `structured()`, its
own fresh repair loop — a fallback model's output shape/wording shouldn't inherit repair turns
built against the primary). A2 §1.5 "version pinning": both methods now take optional
`prompt_name`/`prompt_version` kwargs (the caller's loaded `Prompt.name`/`.version`) and thread
them straight onto the returned `CallMetrics`, so every trace and eval row carries exactly which
versioned prompt file produced it — no separate wiring, since `CallMetrics` is already what
`process_outputs=mask_run_payload` serializes into the trace.
**Takes in:** model id, system prompt, messages, optionally a Pydantic output model (`structured()`),
optionally `prompt_name`/`prompt_version`.
**Gives out:** `LLMResult` or a validated Pydantic object, paired with `CallMetrics` (now also
carrying `prompt_name`, `prompt_version`, `used_fallback_model`).
**Talks to:** `InsightService`, `TextToSqlService`, every specialist/orchestrator/RAG/model-
selection call site, `run_effort_lab.py`, `run_tokenization_lab.py` all call through this instead
of touching the Anthropic SDK directly; `copilot.guardrails.trace_masking` (Day 7).

### `src/copilot/llm/prompts.py` *(day: 3)*
Versioned prompt loader — prompt text lives in reviewable YAML, not buried in Python strings. A
*behaviour* change (tone, grounding rule, output shape) is a new version file (`v2.yaml`); a pure
*capacity* fix (raising `max_tokens`) is edited in place on the existing version.
**Takes in:** a prompt name + version; `prompts/<name>/v<N>.yaml`.
**Gives out:** a validated `Prompt` with `.render_system()` / `.render_user()`.
**Talks to:** `InsightService`, `TextToSqlService` both load their prompts this way.

### `src/copilot/llm/pricing.py` *(day: 3)*
Turns a call's token counts into a USD figure — one source of truth for prices.
**Takes in:** a model ID and token counts (input/output/cache write/cache read).
**Gives out:** `cost_usd(...) -> float`.
**Talks to:** `LLMClient` (every real call), `run_tokenization_lab.py` (cost projections).

### `src/copilot/llm/types.py` *(day: 3)*
The shared result shape every LLM call returns, so logging/LangSmith/tests never branch on which
call path produced it. Holds `CallMetrics` (TTFT, latency, tokens, cost). Day 8, A2 §1.1/§1.5:
`CallMetrics` also carries `prompt_name`/`prompt_version` (which versioned prompt file produced
this call, if any) and `used_fallback_model` (whether `LLMClient._with_fallback()` actually had
to fail over — tells "fallback succeeded" apart from "primary succeeded on the first try").

---

## SQL layer — turning a question into a safe query

### `src/copilot/sql/service.py` — `TextToSqlService` *(day: 3)*
One business question → one validated DuckDB query → real rows. Shows the model only its role's
tables (schema linking) and 3 similar verified examples, validates every candidate query through
all 6 validator layers before running it, and on rejection feeds the exact violations back to the
model as the next turn (self-correction, max 2 retries) rather than giving up or running bad SQL.
Day 7 step 2: its system prompt now appends `canary_line("data_analyst")`.
**Talks to:** `schema.py`, `examples.py`, `validator.py`, `store.py`, `LLMClient`,
`copilot.guardrails.canary` (Day 7).

### `src/copilot/sql/schema.py` *(day: 3)*
Builds the "schema card" shown to the model — only the tables/columns a given role may even be told
about, so the model never writes SQL for data it can't have, which would just waste a repair loop.
**Talks to:** reads from the same source-of-truth as `policy.py` and the Parquet manifest.

### `src/copilot/sql/examples.py` *(day: 3)*
Retrieves 3 golden question/SQL pairs similar to the current question, as few-shot examples —
lexical overlap, not embeddings (the golden set is small enough that a vector index would be
overkill). Examples are role-filtered so a less-privileged role is never shown a more-privileged
query shape.

### `src/copilot/sql/validator.py` *(day: 3)*
The 6-layer validator that catches two failure families before anything runs: structurally unsafe
SQL (wrong table, disguised write, catalog probe), and structurally valid SQL that would still
return a wrong *number* (a ratio column averaged across vendors, a sum after a fan-out join, two
overlapping counts added). Full trap table: `docs/specs/text_to_sql_safety.md`.
**Day 7 step 8, red-team case 8 (`sql_cost_limit`):** `_check_cost_limit` blocks a multi-table
`FROM`/`JOIN` with no `ON`/`USING` condition *unless* `WHERE` references columns from at least
two of the joined tables by their table-qualified name -- catches an unbounded cross join (a DoS
risk: the LIMIT cap bounds the output, not the join computation that produces it) without
false-blocking `gq-025`'s real golden query, a self-join with no join key that's entirely bounded
through `WHERE` instead (`d.SalesMonth = 12 AND n.SalesMonth = 11`). Known, documented limitation:
only a table-qualified `WHERE` column counts as bounding -- an unqualified column filtering one
side of a comma-join is still flagged, a deliberate false-block-over-false-allow tradeoff.
**Talks to:** `sql_rules.yaml` (the rules data), `TextToSqlService` (calls it before running SQL),
`evaluators.py`'s `leakage_free` (re-runs it as a defence-in-depth check), `tests/
test_privacy_leakage_suite.py` (Day 7 step 8's SQL red-team half).

---

## Evals layer — scoring the system against the golden set

### `src/copilot/evals/golden.py` *(day: 3)*
Defines what one golden question looks like and re-checks it against the snapshot.
**Gives out:** typed `GoldenQuestion` objects; `verify()` re-executes every SQL and compares results.

**31 Oct 2026:** `run_rows` executes on its own cursor, so parallel specialists sharing one connection can't interleave results.

### `src/copilot/evals/evaluators.py` *(day: 3)*
Two separate scores per answer: `execution_accuracy` (did it compute the right numbers, or
correctly abstain) and `leakage_free` (independent re-validation of whatever SQL actually ran, so a
future service-level bug still gets caught by the eval suite). Fixed 14 Oct: row comparison used to
require an exact column-name match; now compares by *value*, in column order, per the spec.

### `src/copilot/evals/langsmith_sync.py` + `scripts/push_golden_to_langsmith.py` *(day: 3)*
Keeps one LangSmith dataset (`vendor-copilot-golden-v2`) in sync with
`evals/datasets/golden_v2.jsonl` — full replace, not incremental. The script is the thing you run on
your own machine with your `LANGSMITH_API_KEY`; it makes no LLM calls.

### `src/copilot/evals/effort_lab.py` + `scripts/run_effort_lab.py` *(day: 3)*
Sweeps `effort` (low→max) across the same golden questions and compares execution accuracy,
leakage-free rate, cost and latency at each level — the replacement for a temperature sweep, since
this model generation has no temperature. The script is what you run on your machine with your
`ANTHROPIC_API_KEY`; real money, real calls.

### `src/copilot/evals/tokenization_lab.py` + `scripts/run_tokenization_lab.py` *(day: 3)*
Compares three ways of counting tokens on this project's real prompts — Anthropic's own provider
counter (exact, a real API call), `tiktoken`, and a Hugging Face tokenizer (both local
approximations) — then projects what each would predict for cost per 1,000 requests. Real result
(14 Oct): both local tokenizers undercount badly (tiktoken -41.5%, HF -32.6%), which would make
budgeting on either one understate the real bill.

### `evals/thresholds.yaml` + `scripts/run_eval_gate.py` *(day: 8, isNew: true)*
Day 8, Addendum A2 §1.3: the CI eval gate (`.github/workflows/ci.yml`'s new `eval-gate` job,
PRs targeting main only). "Deterministic-first": the hard floor is the full `uv run pytest`
suite (zero real LLM calls anywhere in it) failing on any failure *not* in the script's own
`_KNOWN_MISSING_DATA_FAILURES` set -- this repo's licence rule means a fixed, documented set of
tests always fails in any environment without the local, never-committed snapshot, this
project's own GitHub Actions run included, and that's expected, not a regression. On top of
that, an `llm_judged` layer (thresholds in `evals/thresholds.yaml`: text-to-SQL execution
accuracy/leakage-free rate, RAG faithfulness/context recall, Model Selection task-type-correct/
reasoning-grounded, Orchestrator plan-coverage/verified-rate) runs only when a real
`ANTHROPIC_API_KEY` *and* the real snapshot/Chroma index are both present -- never true in this
repo's own CI, by the same licence rule, so this layer is correctly SKIPPED there with a clear
message rather than failing the gate over infrastructure that was never supposed to exist in
that environment; it applies identically on your own machine, or a CI environment you
deliberately configure with your own secrets and your own non-sensitive snapshot.
`_CostTrackingLLMClient` wraps a real `LLMClient`, accumulating `cost_usd` from every
`complete()`/`structured()` call (duck-typed drop-in -- no evaluator's signature changes) to
enforce `max_llm_budget_usd` as a hard per-run ceiling, checked before each call against the
running total; hitting it fails the gate outright rather than silently truncating coverage.
**Takes in:** `evals/thresholds.yaml`'s thresholds; (for the `llm_judged` layer) the real
snapshot, Chroma index, and `ANTHROPIC_API_KEY`.
**Gives out:** exit code 0 (gate passed, or `llm_judged` correctly skipped) or non-zero (an
unexpected test failure, a threshold miss, or budget exhaustion), plus a printed report.
**Talks to:** every eval suite this project has (`copilot.evals.evaluators`/`golden`/
`rag_metrics`/`rag_quality`/`model_selection_metrics`/`model_selection_quality`/
`orchestrator_golden`); `copilot.agents.wiring`/`orchestrator`; `copilot.llm.client`
(`LLMClient`, wrapped); `.github/workflows/ci.yml`.

### `docs/determinism.md` *(day: 8, isNew: true)*
Day 8, Addendum A2 §1.7: the determinism note. Draws the same deterministic/non-deterministic
line the eval gate above is built on -- Guardian, input gate, SQL validator, and the
`execution_accuracy`/`leakage_free` evaluators never touch an LLM and always reproduce; planning,
drafting, verifying, and the LLM-judged evals do call one and are openly non-deterministic by
construction (no `seed`/`temperature` on this model generation to pin). Explains what forced
structured output, the repair/redraft loops, the Guardian's unconditional run, the golden-set
evals' numeric tolerance, and prompt version pinning (A2 §1.5, already shipped) each do -- and
don't do -- about that variance. Pure documentation; no code changed.

### `src/copilot/evals/__init__.py`, `src/copilot/insights/__init__.py`, `src/copilot/llm/__init__.py` *(day: 3)*
Empty package markers — no logic, just make the folder importable.

---

## Insights

### `src/copilot/insights/service.py` — `InsightService` *(day: 3)*
A grounded narrative insight for one vendor at a time — the typed, testable refactor of the legacy
analytics repo's `vendor_insights.py`. The model id lives in the prompt YAML, not hardcoded, and
every number the model may use is handed to it explicitly; nothing is looked up by the model itself.
Day 8, A2 §1.1 "graceful degradation": `vendor_insight()` is the first call site to actually use
this pattern — if the narration step fails outright (an outage covering every configured model,
or a repeatedly-malformed response, after `LLMClient`'s own retries and fallback are exhausted),
it returns a `VendorInsight(narration_available=False, narrative=<the deterministic data block as
JSON>, ...)` and a zeroed `CallMetrics(stop_reason="degraded")` instead of raising — the caller
still gets the real, correct numbers for a question the data layer could answer on its own,
rather than a 500.
**Takes in:** a vendor name + the caller's role.
**Gives out:** `VendorInsight` (forced structured output, now with `narration_available: bool`) +
`CallMetrics`.
**Talks to:** `LLMClient`, `prompts/vendor_insight/v1.yaml`, `guard.py`'s masking rules.

---

## API

### `src/copilot/api/main.py` *(day: 2)*
The FastAPI HTTP entry point. Day 2 walking skeleton: `/health` says the process is alive,
`/version` says exactly which build is deployed. Day 8 step 3/4 add the two real endpoints:
`POST /auth/redeem` (an invite code -> a usable API key, the one HTTP-reachable half of
`copilot.api.auth` -- see that module for why there is no HTTP way to *mint* an invite or a
key, only to redeem one) and `POST /ask` (the Orchestrator, behind auth + rate limiting,
streamed over SSE). `_sse_lines()` turns each `copilot.agents.orchestrator.StreamEvent` from
`Orchestrator.stream_answer()` into one `event: <type>\ndata: <json>\n\n` block -- hand-rolled
rather than pulling in `sse-starlette`, since this project's whole stream is "one JSON object
per typed event," nothing a small helper and Starlette's own `StreamingResponse` don't already
cover. It's also where the caller's per-identity daily budget (A2 §1.6) actually accrues:
the run's real `total_cost_usd` isn't known until the trailing `result` event, so it's recorded
there, not before.
**Day 8 step 7: `POST /ask/approve` and the UI.** `/ask/approve` is the one HTTP way to resume a
run `/ask` paused at the approval gate -- a thin wrapper over `Orchestrator.resume_approval`,
gated by its own `require_role("approver", "admin")` dependency (`require_approver_role`, a
*separate* factory call from `/ask`'s `require_any_role` -- these two routes intentionally allow
different role sets, so they must resolve to different dependency callables even though the
factory itself is shared). `GET /` serves `static/index.html`; `/static/*` is a mounted
`StaticFiles` directory for its JS/CSS -- a single self-contained page with no build step, no
framework, talking to this same server's `/auth/redeem`, `/ask` (SSE, parsed by hand with
`fetch`'s `ReadableStream` since `EventSource` can't set an `Authorization` header) and
`/ask/approve`. Both mounted under paths that never collide with the API routes above, so route
order doesn't matter.
**Takes in:** HTTP requests; `RedeemInviteRequest`/`AskRequest`/`ApprovalRequest` bodies; an
`Authorization: Bearer <api-key>` header on `/ask` and `/ask/approve`.
**Gives out:** JSON for `/health`/`/version`/`/auth/redeem`/`/ask/approve`; a `text/event-stream`
body for `/ask`; the static UI for `/` and `/static/*`.
**Talks to:** `copilot.api.auth`/`dependencies`/`rate_limit`; `copilot.agents.orchestrator`
(`Orchestrator`, `OrchestratorResult`, `StreamEvent`); `copilot.secrets` (SSM at start-up,
unchanged from Day 2); `starlette.staticfiles` (the UI's own files).

### `src/copilot/api/dependencies.py` *(day: 8, isNew: true)*
Everything `/ask`/`/auth/redeem` inject via `Depends()`: `get_auth_store`/`get_user_rate_
limiter`/`get_ip_rate_limiter`/`get_user_budget_tracker` (cheap, `@lru_cache`'d singletons) and
`get_orchestrator` (the one expensive, real-key-requiring singleton -- built lazily on first
`/ask` call, exactly `scripts/run_orchestrator_golden.py`'s own real-service wiring reused, so
`/health`/`/version` never fail to start a process missing an `ANTHROPIC_API_KEY` or the real
snapshot/Chroma index). `require_role(*allowed)` is a dependency *factory* (a route states its
own allowed roles) that authenticates the `Authorization` header against `AuthStore` and
returns a `Principal`; `require_any_role` is the one shared instance `/ask` and
`enforce_rate_limits` both depend on, so FastAPI's per-request dependency caching (keyed by
callable identity) runs authentication exactly once per request, not twice.
`enforce_rate_limits(request, principal, ...)` is the per-identity/per-IP/per-identity-daily-
budget guard (A2 §1.6), run after auth resolves a `Principal` and before anything -- the
Orchestrator, even the input gate -- ever sees the request; raises `HTTPException(429)` on the
first of the three checks that fails.

**Day 8 step 7: `_build_checkpointer()`.** The one place that decides which checkpoint store a
real server run gets: local SQLite (unchanged default) when `settings.checkpoint_database_url`
is unset or empty (same empty-string-secret guard `scripts/run_eval_gate.py` already needed for
`ANTHROPIC_API_KEY` -- an unset env var and one set to `""` are not the same thing to
pydantic-settings), a `PostgresSaver` over a `psycopg_pool.ConnectionPool` otherwise. A pool, not
a single `Connection`, because `get_orchestrator()`'s result -- and everything it holds,
including this checkpointer -- is one process-lifetime singleton shared across every concurrent
`/ask` request; a single psycopg `Connection` isn't safe for that, a pool is what it's for.
`.setup()` runs LangGraph's own idempotent migration on every start-up. `Orchestrator` itself
stays storage-agnostic (see its own docstring) -- this function is the only code that imports
`psycopg`/`langgraph.checkpoint.postgres` at all.
**Takes in:** a `Request` (for the client IP) and, via other dependencies, the `Authorization`
header; `settings.checkpoint_database_url` (for `_build_checkpointer`).
**Gives out:** a `Principal`, or raises `HTTPException` (401/403/429); a `BaseCheckpointSaver`
from `_build_checkpointer`.
**Talks to:** `copilot.api.auth`, `copilot.api.rate_limit`, `copilot.agents.wiring`
(`build_executors`), every real service `get_orchestrator` wires up (same list `scripts/
run_orchestrator_golden.py` already names); `langgraph.checkpoint.postgres`/`.sqlite`,
`psycopg_pool` (checkpoint storage only).

### `src/copilot/api/auth.py` -- `AuthStore` *(day: 8, isNew: true)*
Invite-code + API-key authentication (Day 8 step 4). Both are `secrets.token_urlsafe(24)`,
hashed with SHA-256 before ever touching disk -- the raw value is returned to the caller exactly
once (at issue/redeem time) and never again; there is no "show my key" endpoint, by design.
File-backed (`data/auth/auth_store.json`, never committed), loaded fresh per call -- same shape
`copilot.guardrails.input_gate.SpendTracker` already established for "needs to survive a
restart, isn't worth a database yet." An invite redeems exactly once (its hash is marked `used`
in the same write that issues the key). There is no HTTP endpoint that *issues* an invite or an
API key directly -- only `AuthStore.issue_invite`/`.issue_api_key`, called from `scripts/
issue_invite_code.py` on the operator's own machine, and `POST /auth/redeem`, which only ever
*exchanges* an already-issued invite.
**Takes in:** a `Role` + label (issuing); a raw invite code or API key (redeeming/
authenticating).
**Gives out:** the raw invite code / API key (once, at issue time); a `Principal(key_id, role,
label)` from `authenticate()` -- `key_id` (never the raw key) is the stable identity `copilot.
api.rate_limit`'s per-user limiter/budget key on.
**Talks to:** `copilot.guardrails.policy` (`Role`); `scripts/issue_invite_code.py`;
`copilot.api.dependencies`/`main` (every auth-gated route).

### `src/copilot/api/rate_limit.py` *(day: 8, isNew: true)*
Day 8, A2 §1.6: per-identity (API key) and per-client-IP request limits, plus a per-identity
daily cost budget -- on top of (not instead of) Day 7's `InputGate`, which only limits per-
*role* (one noisy API key would otherwise share a `viewer`-wide bucket with every other viewer).
`RequestRateLimiter` is the exact same sliding-window mechanism `copilot.guardrails.input_gate.
RateLimiter` already uses, reused rather than reimplemented, just keyed by an arbitrary identity
string instead of a `Role`. `DailyBudgetTracker` is a thin wrapper around `SpendTracker` itself
(that class's `role: str` parameter is really just a dict key, so a `key_id` fits it exactly),
pointed at its own file (`data/spend/daily_user_spend.json`) so per-user and per-role totals
never share rows.
**Takes in:** an identity string (a `Principal.key_id`, or a client IP) per check; a cost in USD
to record.
**Gives out:** `bool` (allowed or not); today's cumulative spend for an identity.
**Talks to:** `copilot.guardrails.input_gate` (`SpendTracker`, reused); `copilot.api.
dependencies`/`main`.

### `src/copilot/api/static/{index.html,style.css,app.js}` *(day: 8, isNew: true)*
Day 8 step 7: the minimal UI -- chat box, a live agent-status strip (one chip per `StreamEvent
(type="node")`, in the real execution order the graph reported), result badges (verified/
not-verified, Guardian escalated/blocked, pending-review with its `review_id`, pending-approval),
a citations section (one card per `AgentResult` in `OrchestratorResult.results`: agent, status,
confidence, findings, `evidence`), and an approval panel (Approve / Approve-with-edit / Reject,
shown only when `pending_approval` is true) that posts to `/ask/approve`. No framework, no build
step -- vanilla JS, `fetch` for everything, including SSE (parsed by hand: `EventSource` can't
carry an `Authorization` header, so `/ask`'s stream is read via `response.body.getReader()` and
split on blank lines). The API key lives in `localStorage`, this browser only; the thread ID is
a fresh `crypto.randomUUID()` per page load/"New thread" click, kept only in a page-level JS
variable, so the same thread survives an approval round-trip within one conversation. Bundled
into the wheel automatically (`[tool.hatch.build.targets.wheel]` already packages the whole
`src/copilot` tree; confirmed by inspecting a real built wheel's file list).
**Takes in:** nothing server-side -- served as static files by `main.py`'s `/`/`/static/*`
routes; the browser's own form input.
**Gives out:** nothing server-side; renders whatever `/auth/redeem`/`/ask`/`/ask/approve`
return.
**Talks to:** `/auth/redeem`, `/ask`, `/ask/approve` -- this server's own HTTP API, nothing else
(no external CDN, no analytics, no other origin).

---

## RAG / Knowledge layer — the Knowledge agent's retrieval stack (Day 4)

**31 Oct 2026 (`app.js`):** decision badges (Approved, Approved with edits, Rejected, Held back) replace the "decision recorded" line that `renderResult()` used to clear; the Ask button is disabled while a run streams, so one click is one run.

### `knowledge/*.md`, `knowledge/contracts/*.md` *(day: 4)*
The RAG source corpus, not code: 4 methodology-family docs (data dictionary, metric definitions,
decision log, methodology — `public`/`internal`) + 10 synthetic vendor supply-agreement summaries
(`confidential`), each headed `SYNTHETIC` and stating no real contract exists. Every doc opens with
YAML frontmatter (`doc_type`, `vendor`, `version`, `data_class`, `allowed_roles`).
**Talks to:** `copilot.rag.corpus` is the only code that reads these.

### `src/copilot/rag/corpus.py` *(day: 4)*
Parses every knowledge doc's frontmatter + Markdown body into a typed `KnowledgeDoc`.
`check_corpus_against_policy()` recomputes each doc's expected `allowed_roles` from the live
disclosure policy and fails loudly if a doc's hand-authored roles have drifted from it.
**Takes in:** the `knowledge/` directory.
**Gives out:** `list[KnowledgeDoc]`.
**Talks to:** `copilot.guardrails.policy` for `DataClass`/`Role` and the drift check;
`copilot.rag.chunking` reads its output.

### `src/copilot/rag/chunking.py` *(day: 4)*
Splits each `KnowledgeDoc`'s body into `Chunk`s at every Markdown heading (the real semantic
boundaries in this hand-curated corpus), re-splitting by paragraph (with overlap) only if one
section runs over ~1000 chars — comfortably under the embedder's truncation point. Carries the
doc's permission metadata (`data_class`, `allowed_roles`) onto every chunk.
**Takes in:** `list[KnowledgeDoc]`.
**Gives out:** `list[Chunk]`, each with a stable `chunk_id` and a `content_hash` of its text.
**Talks to:** `copilot.rag.store` reads its output; `copilot.rag.corpus` for the input type.

### `src/copilot/rag/embeddings.py` *(day: 4)*
`Embedder` protocol + `SentenceTransformerEmbedder` (local `all-MiniLM-L6-v2`, 384-dim, lazy-loaded
so constructing it never triggers a download) + `FakeEmbedder` (deterministic, no network — used by
every test in this repo). The real model's weights come from the Hugging Face Hub, which this build
sandbox's proxy blocks, so the real embedding run is `scripts/build_rag_index.py` on your machine.
**Takes in:** chunk text (or a query string).
**Gives out:** one float vector per text.
**Talks to:** `copilot.rag.store.ChunkStore.upsert`/future retrieval code call `embed()`.

### `src/copilot/rag/store.py` *(day: 1)*
`ChunkStore` wraps one Chroma collection (`PersistentClient`, `data/chroma/` — gitignored, same
never-commit-derived-data rule as the Parquet snapshot). `upsert()` is keyed by each chunk's
`content_hash`, not its `chunk_id`, so a full corpus rebuild skips every chunk whose text hasn't
actually changed. `query()` is plain vector search, now with an optional `where` metadata filter
(Day 4 step 5: `copilot.rag.permissions.PermissionedRetriever` passes
`{"data_class": {"$in": [...]}}` so ineligible chunks are excluded inside the ANN search itself,
not dropped from an already-fixed-size result afterwards — `None`, the default, is what
`copilot.rag.retrieval.HybridRetriever` (step 4) still uses, unrestricted).
**Takes in:** `list[Chunk]` + an `Embedder` (for `upsert`); a query vector + optional `where`
filter (for `query`).
**Gives out:** an `UpsertReport` (embedded vs. already-current counts); nearest-chunk tuples.
**Talks to:** `copilot.rag.embeddings` for vectors; `copilot.guardrails.policy`'s `DataClass`/`Role`
types for the metadata it stores and reads back; `copilot.rag.retrieval` and
`copilot.rag.permissions` both call `query()`.

### `src/copilot/rag/retrieval.py` *(day: 4)*
`BM25Index` (lexical, in-memory, rebuilt from the chunk list each time — no incremental-update
story at this corpus size) + `reciprocal_rank_fusion()` (plain RRF: `sum(1/(k+rank))` across
rankings, default `k=60`) + `fuse_rankings()` (turns two ID rankings into the final
`RetrievedChunk` list — shared with `copilot.rag.permissions.PermissionedRetriever`, step 5, so
both classes assemble results identically) + `HybridRetriever`, which runs both a BM25 search
and a `ChunkStore.query()` vector search over the same chunk list and fuses their rankings via
`fuse_rankings()`. Reranker is this step's cut item (see `docs/PROJECT_PROGRESS.md`) —
`RetrievedChunk` already carries the full chunk text, so one can be added later as a third stage
without changing this module's contract. No permission filtering here — step 5 wraps this.
**Takes in:** `list[Chunk]` (to index for BM25 and to resolve IDs back to chunks), a `ChunkStore`,
an `Embedder`, and a query string at retrieve time.
**Gives out:** `list[RetrievedChunk]` — each with the matched `Chunk`, its fused RRF score, and
its rank in each underlying ranking (`None` if it didn't appear in that one).
**Talks to:** `copilot.rag.chunking` for `Chunk`; `copilot.rag.store` for vector search;
`copilot.rag.embeddings` to embed the query text; `copilot.rag.permissions` reuses
`fuse_rankings()`/`BM25Index`/`RetrievedChunk`.

### `src/copilot/rag/permissions.py` *(day: 4)*
`PermissionedRetriever` — role-aware counterpart to `HybridRetriever`: same RRF fusion (shares
`retrieval.fuse_rankings`), but every chunk either ranking can return is first scoped to what
the given role may see. Authority is the live `DisclosurePolicy.can_view(role, data_class)`,
re-derived every call — never the chunk's own `allowed_roles` field, even though
`copilot.rag.corpus.check_corpus_against_policy` already checks the two agree at ingest time.
The filter runs *inside* the vector query (a Chroma `where={"data_class": {"$in": [...]}}`
pushed into `ChunkStore.query()`), not as a post-hoc drop after a fixed-size result set — the
latter would silently return fewer than `n_results` whenever permissions trim the field. BM25
has no per-call filter to push into, so the same principle is enforced one layer up: the
role-scoped BM25 index is built from only the visible chunks in the first place.
**Takes in:** `list[Chunk]`, a `ChunkStore`, an `Embedder`, a `DisclosurePolicy`; a query string
+ `Role` at retrieve time.
**Gives out:** `list[RetrievedChunk]`, same shape as `HybridRetriever`'s.
**Talks to:** `copilot.rag.retrieval` for `BM25Index`/`fuse_rankings`/`RetrievedChunk`;
`copilot.rag.store` (its `where`-filtered `query()`); `copilot.guardrails.policy` for
`DisclosurePolicy`/`Role`/`DataClass`.
*(day: 6 addition)* `chunk_by_id(chunk_id) -> Chunk | None` — plain lookup against the full
corpus this retriever was built with, added for the Knowledge specialist
(`copilot.agents.specialists.run_knowledge`), which needs a *cited* chunk's `data_class` after
the fact; `CorrectiveRagResult` only reports chunk ids, not the chunks themselves.

### `src/copilot/rag/corrective.py` *(day: 4)*
`CorrectiveRagService` — the Corrective RAG loop, compiled as a LangGraph `StateGraph`:
retrieve → grade → (generate | rewrite → retrieve again | abstain). Grading and query-rewriting
are their own versioned prompts (`prompts/crag_grade/`, `prompts/crag_rewrite/`); generation is
`prompts/crag_generate/`. Wraps a `PermissionedRetriever` (step 5) behind a `Retriever` Protocol,
so this loop is permission-aware by construction. Simplified from the CRAG paper on purpose: no
external web-search fallback (this system answers from one internal corpus by design — ADR-002)
— "not enough relevant chunks" rewrites the query and retries the *same* corpus instead, bounded
by `MAX_CORRECTIONS` (mirrors `copilot.sql.service.MAX_SELF_CORRECTIONS`), then abstains honestly
rather than generate from weak grounding. Never trusts a grade or citation for a chunk id that
wasn't actually shown to the model. Day 7 step 2: `_grade`/`_rewrite`/`_generate` each append
their own `canary_line("knowledge_grade"/"knowledge_rewrite"/"knowledge_generate")`.
**Takes in:** a question, a `Role` (per call, not per instance).
**Gives out:** a `CorrectiveRagResult` — a grounded answer + the chunk ids it actually cited, or
an explicit abstention + reason, plus cost/latency/call accounting (same shape as
`TextToSqlResult`).
**Talks to:** `copilot.rag.permissions`/`copilot.rag.retrieval` (via the `Retriever` Protocol and
`RetrievedChunk`); `copilot.llm.client`/`copilot.llm.prompts` for the three LLM calls;
`copilot.guardrails.canary` (Day 7).

### `scripts/build_rag_index.py` *(day: 4)*
Loads the corpus, checks it against the live disclosure policy, chunks it, embeds with the real
local model, and upserts into `data/chroma/` — prints how many chunks were actually (re-)embedded
vs. already up to date.
**Needs:** nothing but normal internet access (no API key — the model is local and free to run).
**Talks to:** every `copilot.rag.*` module above, in pipeline order.

### `scripts/run_rag_eval.py` *(day: 4)*
Day 4 step 7's eval runner. Retrieval metrics (recall@k, MRR — `copilot.evals.rag_metrics`) are
free and run against whatever's already in `data/chroma/`. `--quality` additionally runs the
cut-down Ragas pair (`copilot.evals.rag_quality`: faithfulness + context_recall) via real
`CorrectiveRagService`/LLM calls — costs money, off by default.
**Needs:** the real Chroma index (`build_rag_index.py` first); `--quality` needs `ANTHROPIC_API_KEY`.
**Talks to:** `copilot.evals.rag_golden`/`rag_metrics`/`rag_quality`, `copilot.rag.permissions`,
`copilot.rag.corrective`.

### `src/copilot/evals/rag_golden.py`, `rag_metrics.py`, `rag_quality.py` *(day: 4)*
The RAG eval harness (Day 4 step 7). `rag_golden`: 20 labelled questions
(`evals/datasets/rag_golden_v1.jsonl`) against the real knowledge corpus, each naming a
`doc_type`/`vendor` + a verbatim `must_contain` phrase rather than a `chunk_id` directly, so the
dataset survives a re-chunk; `relevant_chunk_ids()` resolves it at eval time. `rag_metrics`:
pure-arithmetic `recall_at_k()`/`reciprocal_rank()` + means — no LLM, runs for real anywhere.
`rag_quality`: `faithfulness()`/`context_recall()`, the sprint's Ragas suite cut down to two
(its own cut-first note) — small LLM-judge calls reusing `copilot.evals.evaluators.EvalScore`
rather than the `ragas` package, consistent with this repo's existing hand-written evaluators.
**Talks to:** `copilot.rag.chunking`/`corpus` (to resolve relevance); `copilot.llm.client` (the
quality judges); `copilot.evals.evaluators` for `EvalScore`.

---

## ML tools — the Forecasting & Risk and Inventory Planning agents' tools (Day 5)

### `src/copilot/ml/metrics.py` *(day: 5)*
WAPE, MASE, bias -- the three forecast-accuracy metrics the sprint doc names (not MAPE, which
the analytics repo's own `forecast_backtest.py` already found unreliable near-zero actuals).
**Takes in:** parallel actual/forecast sequences (plus the training series, for MASE's scale).
**Gives out:** one float per metric.
**Talks to:** nothing -- pure NumPy arithmetic, no fakes needed, same category as
`copilot.evals.rag_metrics`.

### `src/copilot/ml/forecast.py` — `forecast_demand()` *(day: 5)*
Demand forecast tool: ETS vs naive, honest out-of-sample accuracy from a rolling-origin
backtest (never an in-sample fit -- ADR-000 item 2 is exactly that mistake, in the Excel tool
this project replaces). Matches the analytics repo's `forecast_backtest.py` methodology
(one-month-ahead, expanding window) so the numbers are comparable.
**Takes in:** a `ForecastRequest` (portfolio or one vendor, horizon in months).
**Gives out:** a `ForecastResult` -- point forecasts, which model won the backtest, and the
WAPE/MASE/bias for both models, plus `seasonality_note` explaining why true seasonal-naive
isn't estimable with only 12 months of history (R3 in `docs/RAID.md`).
**Talks to:** `copilot.data.store` (reads `portfolio_monthly_demand` / `vendor_monthly_demand`),
`copilot.ml.metrics`, `statsforecast.models.AutoETS`. Consumed by `copilot.ml.inventory`
(`demand_stats_from_backtest`) and will be a LangGraph tool for the Forecasting & Risk agent
(Day 6).
**Real numbers already run in this sitting** (not deferred to your machine -- no API key or
network needed): portfolio WAPE 11.5%, matching the analytics repo's own documented "naive
11.8%" baseline as a sanity check; both ETS and naive converge to nearly the same forecast on
the portfolio series (AutoETS's auto-selected trend reduces to effectively no trend on this
short, noisy series) -- a real finding, not a bug, logged in `docs/BUILD_LOG.md`.

**30 Oct 2026:** `forecast_warnings()` adds plain-English cautions to `ForecastResult.warnings`: under 24 months of history (seasonality can't be learned), and a last month 20% or more above or below the median earlier month (both models start from it, so the next months are likely over- or under-forecast). On the real snapshot both fire: December 2024 is 38% above the typical month.

**31 Oct 2026:** `_load_series` queries on its own cursor; a shared connection used by parallel specialists returned None from `.df()`.

### `src/copilot/ml/inventory.py` — `compute_inventory_plan()` *(day: 5)*
Safety stock, reorder point, EOQ -- standard OR formulas (Silver/Pyke/Peterson; Wilson 1913 for
EOQ), from a forecast's output. `demand_stats_from_backtest()` is the bridge from a
`ForecastResult` to these formulas' (mean, std-dev) inputs -- deliberately uses historical
month-over-month variability, not variance across the forecast points themselves, because a
flat (naive) forecast has zero variance by construction and would otherwise silently hand back
a zero safety stock.
**Takes in:** an `InventoryRequest` (mean/std demand per period, lead time, service level,
ordering and holding costs) or a `ForecastResult` via `demand_stats_from_backtest()`.
**Gives out:** an `InventoryPlan` (z-score, safety stock, reorder point, EOQ).
**Talks to:** `copilot.ml.forecast` (`ForecastResult`), `scipy.stats.norm` (service level ->
z-score). Will be a LangGraph tool for the Inventory Planning agent (Day 6).

### `src/copilot/ml/risk_classifier.py` — `classify_sku_risk` (Random Forest + XGBoost) *(day: 5, isNew: true)*
SKU risk classifier for ADR-000 item 1: predicts `is_at_risk` (HealthStatus `Loss Making`/
`At Risk`) from operational features, leaking-feature-excluded by construction. `LEAKING_FEATURES`
excludes `ProfitMargin`/`MarkupPct`/`NetMarginAfterExcisePct` (the real view's margin family that
produces the label) **and** `SalesToPurchaseRatio` -- confirmed algebraically equal to
`StockTurnover * (1 + MarkupPct)`, so it re-derives `ProfitMargin` even though it isn't itself a
raw margin column; found by running the leaky/safe comparison and seeing it dominate the safe
model's SHAP drivers when left in. `make_synthetic_skus()` builds a fixture from one shared latent
"SKU health" factor `z`, with `ProfitMargin` thresholded directly (plus 3% label noise) so the
leakage story is real, not just labelled -- real per-SKU data stays out of this repo (licence
guard; `docs/RAID.md` R1).
**Takes in:** a SKU-row DataFrame with `vw_PortfolioHealth` column names + `HealthStatus`.
**Gives out:** `ClassifierResult` -- accuracy, F1, calibration curve, and (Random Forest only)
SHAP-ranked top drivers; `compare_models()` runs all 4 combinations (RF/XGBoost x leaky/safe) on
one split.
**Talks to:** `sklearn.ensemble.RandomForestClassifier`, `xgboost.XGBClassifier`,
`shap.TreeExplainer`. Will be a LangGraph tool for the Forecasting & Risk agent (Day 6).
**Real-data run:** `scripts/train_risk_classifier.py` on your own `vw_PortfolioHealth` export --
this module's own numbers (synthetic fixture, n=2000) are RF accuracy 0.834->0.820 / F1
0.291->0.211 and XGBoost accuracy 0.898->0.886 / F1 0.667->0.596 (leaky -> leakage-safe); the
direction (leakage inflates both) is the real finding, the exact figures are not — synthetic data.

### `src/copilot/ml/run_log.py` *(day: 5, isNew: true)*
CSV run-log for all three ML tools -- MLflow was cut-first per the sprint doc; this is the
plain-CSV replacement. One `log_*_run()` builder per tool flattens its result into a flat
`RunLogEntry` row (`params`/`metrics` JSON-encoded into single cells) and appends it, writing the
header on first use.
**Takes in:** a `ForecastResult` / `InventoryPlan` / `ClassifierResult` + a CSV path.
**Gives out:** nothing returned to the caller beyond the `RunLogEntry` written; the file itself is
the record.
**Talks to:** `copilot.ml.forecast`, `copilot.ml.inventory`, `copilot.ml.risk_classifier` (reads
each one's result type); `scripts/train_risk_classifier.py` calls `log_classifier_run()`.

---

## Model Selection Agent -- Addendum A1 (Day 5 step 6)

### `src/copilot/agents/model_selection.py` — `ModelSelectionAgent` *(day: 5)*
LangGraph propose -> critique -> revise -> abstain loop, same shape as
`copilot.rag.corrective.CorrectiveRagService` applied to picking a model instead of grounding
an answer -- the direct precedent Addendum A1 names. Picks from a fixed, closed
`MODEL_CATALOG` (never invents a model family): `random_forest`/`xgboost` and `ets`/`naive` are
backed by real tools already built here (`copilot.ml.risk_classifier`, `copilot.ml.forecast`);
`kmeans`/`logistic_regression`/`linear_regression` are catalog entries only, not yet
implemented as tools. The "revise" step is pure bookkeeping (no LLM call) -- unlike
`CorrectiveRagService`'s "rewrite" step, which needs an LLM to creatively reformulate a search
query, revision here only has to forward the critique's already-structured
`concerns`/`suggested_model_family` into the next proposal.
**Takes in:** a plain-text data-science requirement.
**Gives out:** a `ModelSelectionResult` -- accepted `task_type`/`model_family`/`reasoning`, or
an explicit abstention + reason, plus cost/latency/call accounting.
**Talks to:** `copilot.llm.client`/`copilot.llm.prompts` (`model_selection_propose`/`_critique`
v1.yaml); `copilot.evals.model_selection_metrics`/`model_selection_quality` (the eval harness);
`scripts/run_model_selection_eval.py`.

### `src/copilot/evals/model_selection_golden.py`, `model_selection_metrics.py`, `model_selection_quality.py` *(day: 5)*
The Day 5 step 6 eval harness, same free/judged split as the RAG harness. `model_selection_golden.py`:
8 requirements (`evals/datasets/model_selection_golden_v1.jsonl`), 2 per task type, each naming
an `expected_task_type` and a *set* of `acceptable_model_families` (not one exemplar -- the
catalog genuinely offers more than one reasonable pick for classification/forecasting).
`model_selection_metrics.py`: `task_type_correct`/`model_family_acceptable` -- free, pure
catalog-membership checks, no LLM needed. `model_selection_quality.py`: `reasoning_grounded` --
the one LLM-judge call (Addendum A1's "evaluated with LLM evals"), scoring whether the agent's
final reasoning is actually grounded in what the requirement said versus generic ML boilerplate
that a free check can't tell apart from real grounding.
**Talks to:** `copilot.agents.model_selection` (`ModelSelectionResult`, `all_model_families`);
`copilot.evals.evaluators` (reused `EvalScore`); `copilot.llm.client`/`copilot.llm.prompts`
(`model_selection_judge` v1.yaml); `scripts/run_model_selection_eval.py`.

---

## Multi-agent system -- Orchestrator + 5 specialists (Day 6)

### `src/copilot/agents/contracts.py` *(day: 6, isNew: true)*
`TaskSpec`/`AgentResult` -- the typed handoff contracts C3 requires so no specialist passes free
text to another. `TaskSpec` is what the Orchestrator hands one specialist: `objective` +
`constraints` (a dict, not prose, so a node reads a known key instead of re-parsing), a `role`,
and an `AgentBudget` (steps/LLM calls/cost/latency ceiling, defaults 1/3/$0.05/30s, plus
`effort`). `AgentResult` is what comes back: condensed `findings` (C3's <=1500-token target),
`evidence`, a `status` of ok/partial/failed, `gaps` when partial, and -- the field the Guardian
(Day 7) will read -- `data_classes`, filled by the specialist itself from `DisclosurePolicy`,
never inferred downstream. `AgentResult.exceeds()` is the check `copilot.agents.orchestrator.
_run_specialist` (Day 6 step 5) actually runs after a specialist returns, to decide `ok` vs
`partial`. `AgentBudget.effort` (Day 6 step 5) is an `Effort | None` -- this generation's
sampling lever, since `copilot.llm.client`'s module docstring already established that this
Anthropic SDK/model generation has no `temperature` parameter at all; `None` lets a specialist
fall back to its own prompt's `effort` default.
**Takes in:** nothing at import time -- pure Pydantic contracts.
**Gives out:** `TaskSpec`, `AgentResult`, `AgentBudget`, `AgentName` (the closed 5-name Literal:
data_analyst/forecasting_risk/inventory_planning/knowledge/action), `AgentStatus`.
**Talks to:** `copilot.guardrails.policy` (`DataClass`, `Role`); `copilot.llm.client` (`Effort`).
Deliberately does **not** reuse `TextToSqlResult`/`CorrectiveRagResult`/`ModelSelectionResult`
as the envelope -- those stay each service's own return type; the Orchestrator wraps each into
an `AgentResult` rather than those services growing orchestrator-shaped fields.

### `src/copilot/agents/specialists.py` *(day: 6, isNew: true)*
The five specialist nodes (C3 roster), each a plain `TaskSpec -> AgentResult` function wrapping
an already-tested service -- no new logic, just the C3 contract on top.
- `run_data_analyst(spec, sql_service, policy=None, effort=None)` -- wraps
  `TextToSqlService.answer()`; `data_classes` comes from a new helper, `_sql_data_classes(sql,
  policy)`, which parses the generated SQL with sqlglot and looks up every referenced table's
  class via `DisclosurePolicy.class_of()` -- not self-reported by the SQL service, same
  "the policy is the one source of truth" posture `copilot.rag.permissions` takes.
- `run_forecasting_risk(spec, con=None, risk_df=None, compute_shap=False)` -- always runs a real
  `forecast_demand()` against this repo's own snapshot (`spec.constraints["level"]` =
  portfolio/vendor); the SKU risk-classifier half only runs when
  `spec.constraints["run_risk_classifier"] == "true"`, and against `make_synthetic_skus()`
  unless the caller supplies a real `risk_df` -- this repo's licence-safe snapshot has no
  SKU-level features, same limitation Day 5's classifier had. `forecast_result_for_inventory()`
  is a small sibling that returns the raw `ForecastResult` the Orchestrator (step 3) will chain
  into Inventory Planning.
- `run_inventory_planning(spec, forecast)` -- wraps `compute_inventory_plan()`, fed by
  `demand_stats_from_backtest(forecast)` exactly as Day 5's real run did; cost/service-level
  constraints read from `spec.constraints` with Day 5's own real-run defaults.
- `run_knowledge(spec, rag_service, retriever)` -- wraps `CorrectiveRagService.answer()`;
  `data_classes` comes from looking up each `cited_chunk_ids` entry via the new
  `PermissionedRetriever.chunk_by_id()` (see that file's entry above).
- `run_action(spec, llm, effort=None)` -- the one specialist with its own prompt
  (`prompts/action_draft/v1.yaml`), drafting a `renegotiation_email` or
  `reorder_recommendation` via `LLMClient.structured()` into `ActionDraft`
  (`subject`/`body`). Always returns `status="partial"` with a gap stating the draft hasn't
  passed the Guardian/an approver yet (Day 7) -- this function never sends anything.
Day 7 step 2: `run_action`'s system prompt now appends `canary_line("action")` -- any leak of
that marker into a final answer is what `Guardian._check_canary` catches.
**Takes in:** a `TaskSpec` plus each specialist's already-constructed dependency
(`TextToSqlService`, a DuckDB connection, a `ForecastResult`, a `CorrectiveRagService` +
`PermissionedRetriever`, an `LLMClient`).
**Gives out:** `AgentResult` for each; `ActionDraft`, `DraftType` are also exported.
**Talks to:** `copilot.sql.service`, `copilot.ml.forecast`/`inventory`/`risk_classifier`,
`copilot.rag.corrective`/`permissions`, `copilot.llm.client`/`prompts`,
`copilot.guardrails.policy`, `copilot.guardrails.canary` (Day 7).

**30 Oct 2026:** `run_data_analyst` appends a "Units:" line from `copilot.data.units`; `run_forecasting_risk` states that demand is units sold, labels bias in units, passes every forecast warning through as a "WARNING:" line, and reports confidence "low" when there are warnings.

**31 Oct 2026:** `run_action` uses `ACTION_DRAFT_NOTE` as its status gap and, when the plan has no `vendor_name`, calls `identify_vendor()` against the snapshot vendor list (full name, or a short name like "Jim Beam"; returns None rather than choosing between two matches).

**31 Oct 2026, later:** `resolve_level()` decides portfolio vs vendor for forecasting and inventory planning and returns the "Level:" line both now lead their findings with; inventory findings also state units, assumed inputs and the forecast's warnings.

### `prompts/action_draft/v1.yaml` *(day: 6, isNew: true)*
The Action specialist's one prompt. System prompt states the vendor-facing audience rule
(public facts + that vendor's own terms only, for a `renegotiation_email`; internal figures
allowed for a `reorder_recommendation`) as an instruction to the model -- real enforcement is
the Guardian (Day 7), not this prompt; `run_action()`'s `gaps` says so explicitly.

### `src/copilot/agents/orchestrator.py` -- `Orchestrator` *(day: 6, isNew: true)*
Typed plan -> `Send` fan-out -> join -> draft -> verify -> (finalize | revise_draft -> draft...),
compiled as a LangGraph graph (C3/C7). `_plan` (one LLM call, `OrchestratorPlan`/`PlannedTask`)
turns the user's question into a list of specialist tasks; `_fan_out` is a *routing function*,
not a node -- it returns one `Send` per planned task so independent tasks run as separate
parallel `run_specialist` invocations (LangGraph's mechanism for exactly this), or a single
`Send("draft", ...)` when the plan is empty, since `run_specialist` never running would otherwise
leave the static `run_specialist -> draft` edge untraversed. `results` is `Annotated[list[
AgentResult], operator.add]` -- LangGraph's reducer pattern for collecting parallel branch
outputs back into one state key (the "join"). `_draft` (one LLM call, `DraftAnswer`) writes the
answer the user will see if it passes verification, citing which task each figure came from, and
names any disagreement it notices between specialists in `conflicts_noted` -- **logged only,
never resolved or re-queried**, the sprint doc's Day 6 cut-first item. On a redraft it also
reads `verify_feedback` out of state and folds it into the prompt as `feedback_block`.
**Day 6 step 4, the Verifier (C3/C7):** `_verify` (one more LLM call, `VerifierVerdict` via the
`orchestrator_verify` prompt) scores the draft against the specialist findings it was supposed
to be grounded in -- `grounded` (every number traces to a finding), `citations_ok`, `sufficient`,
and any `contradictions` between findings the draft papered over; `VerifierVerdict.passed` is
the AND of the first three and "no contradictions". `_route_after_verify` is a pure routing
function (no LLM call, no state mutation -- mirrors `ModelSelectionAgent._route_after_critique`):
passes -> `finalize`; fails and `verify_attempt < MAX_VERIFICATION_LOOPS` (2) -> `revise_draft`;
otherwise `finalize` anyway, flagged `verified=False` rather than looping forever.
`_revise_draft` is pure bookkeeping (no LLM call -- mirrors `ModelSelectionAgent._revise`):
turns the verdict's `feedback`/`contradictions` into `verify_feedback` text and increments
`verify_attempt`, then loops back to `draft`. `_finalize` assembles the `OrchestratorResult`,
summing each specialist's own cost/latency/llm_calls in exactly once regardless of how many
draft/verify loops ran (that summation moved out of `_draft`, which can now run more than once,
into this one-time-only node). A specialist executor that raises, or a planned agent with no
executor registered, becomes a `status="failed"` `AgentResult` with the reason in `gaps` rather
than crashing the whole plan.
**Day 6 step 5: per-agent budgets, enforced.** `_run_specialist` runs the executor through a
single-worker `ThreadPoolExecutor`, bounded by `task.budget.max_latency_s`; a specialist that
doesn't return in time becomes `status="failed"` with a "timed out after Ns" gap instead of an
unbounded wait (the Orchestrator stops waiting -- it can't force arbitrary sync code to actually
stop, same honest limit every `concurrent.futures`-timeout approach has). After an `ok` result
returns, `AgentResult.exceeds(task.budget)` is checked for real now (step 1 defined it, nothing
called it); an overage downgrades the result to `status="partial"` with the specific cost/
latency/llm_calls overage named in `gaps`, so a specialist that quietly blew its budget is never
reported as if nothing happened.
**Day 6 step 6: a local SQLite checkpointer, and per-agent LangSmith run names/tags.**
`Orchestrator(..., checkpoint_path=...)` compiles the graph with a `langgraph.checkpoint.sqlite.
SqliteSaver` over that file (a plain `sqlite3.Connection`, `check_same_thread=False` since
`_run_specialist` calls into a thread pool); `answer(..., thread_id=...)` is the checkpoint key
-- a caller can resume or inspect one run's state later (`select * from checkpoints where
thread_id = ...`), which is also what LangGraph Studio would otherwise visualize -- **Studio
itself is this step's cut-first item** (an external tool to point at this process, not code to
build). With no `checkpoint_path`, nothing changes (`checkpointer=None`, same as before step 6).
`_ls_extra(node, role, **tags)` builds a `langsmith.run_helpers.LangSmithExtra` (`name="
orchestrator.<node>"`, `tags=["orchestrator", node, f"role:{role}", ...]`), passed as
`langsmith_extra=` to each of `_plan`/`_draft`/`_verify`'s own `LLMClient.structured()` call --
`traceable`'s own call-time override, no change needed to `LLMClient` itself -- so a LangSmith
trace can tell which orchestrator node (and which redraft attempt) a given LLM call belongs to,
instead of every call showing up as the same generic `LLMClient.structured` run.
`copilot.agents.specialists.run_action` tags its own call the same way
(`name="specialist.action"`, tagged with `draft_type`); the other four specialists delegate to
Day 3-5 services (`TextToSqlService`, `CorrectiveRagService`) whose internal LLM calls aren't
yet agent-tagged -- threading tags through those pre-existing services is out of this step's
scope, noted here rather than silently left undone.
**Day 7 step 4: the Guardian, non-bypassable.** `finalize` no longer edges to `END` directly --
it edges to a new `guardian` node (`_guardian_node`, wrapping `copilot.guardrails.guardian.
Guardian`), which reviews the finished `OrchestratorResult`, writes an audit-log row
(`log_decision`), and replaces `answer` with the verdict's `safe_answer` (the raw draft never
reaches a caller; the full verdict is kept on `OrchestratorResult.guardian_verdict`). Every path
from `plan` to `END` now passes through `guardian` -- `tests/test_orchestrator.py::
test_every_path_to_end_passes_through_guardian` asserts this against the *compiled* graph's own
`get_graph()` edges, not `_build_graph`'s source.
**Day 7 step 5: the approval gate (C5).** An Action draft the Guardian allowed/redacted (never
one it already BLOCKed/ESCALATEd) stops one hop short of `END`: `_route_after_guardian` (pure
routing, no LLM call) sends it to `_approval_gate` instead, which calls LangGraph's `interrupt()`
with the draft + verdict as payload, pausing the run until `resume_approval(thread_id, decision,
approver_role=, edited_answer=)` sends back `Command(resume=...)`. `resume_approval` checks
`approver_role in {"approver", "admin"}` in plain Python *before* touching the graph, so an
unauthorized caller can't resume a paused thread even knowing its `thread_id`. Three outcomes:
`"approve"` keeps the Guardian's `safe_answer` as-is; `"reject"` replaces `answer` with a fixed
rejection message; `"edit"` re-runs the approver's new text through `self._guardian.review()`
before accepting it (an edit is unreviewed text -- it could reintroduce exactly what the
original draft didn't have) and uses *that* verdict's `safe_answer`, not the raw edit. Every
branch logs an `"approval_decision"` row via `log_approval`. **Needs a real checkpointer to mean
anything** (`interrupt()`/`Command(resume=...)` require one -- confirmed against a real
`SqliteSaver` with a throwaway smoke script before wiring this in; resuming without one raises
`RuntimeError` from LangGraph itself): an `Orchestrator` built with no `checkpoint_path` skips
the gate entirely (`_route_after_guardian` routes straight to `END`) rather than pausing on a run
nothing can ever resume. `OrchestratorResult.pending_approval` is set only by `answer()`'s own
wrapper when `final_state` carries a `__interrupt__` key -- it's never written into graph state
itself, so a resumed/decided result always reports `pending_approval=False`.
**Day 8, ADR-006 question 2: visible ESCALATE status.** `_guardian_node` (and `_approval_gate`'s
edit-re-review branch) now generates a `review_id` (uuid4) whenever a verdict's `outcome ==
"escalate"`, passes it to `log_decision(..., review_id=)` so the audit-log row and the caller's
object share one join key, and sets `OrchestratorResult.pending_review` to a `PendingReview
(review_id, reason_codes)` -- `None` for every other outcome. `answer` is still the Guardian's
`_ESCALATE_MESSAGE` text either way; `pending_review` is the structured status a caller (`/ask`,
the UI) branches on instead of parsing that text, replacing Day 7's actual behaviour (an
ESCALATE was fully reviewable only by grepping `guardian_log.jsonl` by hand) with the "visible
pending review" ADR-006 decided on, without changing the Guardian's own checks or severity
ordering (both confirmed as-shipped by that ADR).
**Day 8 step 3: `stream_answer()`, for the API's `/ask` SSE endpoint.** `answer()` is now a
two-line wrapper that drains a new generator, `stream_answer()`, for its last event -- the
input-gate check, the graph run (now via `self._graph.stream(..., stream_mode="updates")`
instead of `.invoke()`), the `__interrupt__`-detection, and `InputGate.record_spend` all moved
there unchanged, so there's exactly one copy of that logic rather than two that could drift.
`stream_answer()` yields a `StreamEvent(type="node", node=<name>)` for each graph node LangGraph
reports as it actually runs (confirmed against a throwaway probe script: `stream_mode="updates"`
yields one `{node_name: partial_state}` dict per node, in execution order, and an `
"__interrupt__"` key in place of a node name when `_approval_gate` pauses the run), then exactly
one trailing `StreamEvent(type="result", result=<OrchestratorResult>)` -- the same object
`answer()` has always returned, `pending_approval`/`pending_review` included. `answer()` itself
is unchanged from a caller's perspective (same signature, same return type, same tests pass
unmodified); `/ask` is the first caller of `stream_answer()` directly, to forward each node
event as a server-sent "agent is now doing X" update instead of one blocking call for the whole
multi-specialist run.
**Day 8 step 7: `checkpointer`, for Postgres in production.** A new, optional constructor
parameter alongside `checkpoint_path`: pass any pre-built `BaseCheckpointSaver` (a
`PostgresSaver`, in `copilot.api.dependencies.get_orchestrator`'s case) and it's used as-is,
taking priority over `checkpoint_path` if both are given. This module still never imports
`psycopg` or anything Postgres-specific -- it stays storage-agnostic, calling only the
`BaseCheckpointSaver` interface, exactly as it already did for `SqliteSaver`; building *which*
concrete checkpointer, and from what connection string, is the caller's job. `checkpoint_path`
itself is unchanged and still the simplest path for local dev and every existing test.
**Takes in:** an `LLMClient`, `executors: dict[AgentName, SpecialistExecutor]` -- the Day 6
step 2 `run_*` functions, wired in by the caller (never constructed here: each needs a
different real dependency the Orchestrator has no business reproducing) -- plus a question,
`Role`, and optional `thread_id` at call time; optional `checkpoint_path`/`checkpointer`/
`guardian` at construction time. `resume_approval` additionally takes `thread_id`, a decision
(`"approve"|"edit"|"reject"`), the approver's `Role`, and an optional `edited_answer`.
**Gives out:** `OrchestratorResult` (plan, every `AgentResult`, the drafted answer,
`conflicts_noted`, `verified`/`verify_attempts`, summed cost/latency/llm_calls across plan +
every specialist + every draft/verify attempt, `guardian_verdict`, `pending_approval`,
`approval_decision`) from `answer()`; `stream_answer()` gives the same, wrapped one-per-node in
`StreamEvent`s plus a trailing `StreamEvent(type="result", ...)` carrying it.
**Talks to:** `copilot.agents.contracts` (`TaskSpec`/`AgentResult`/`AgentBudget`/`AgentName`);
`copilot.llm.client`/`prompts` (`orchestrator_plan`/`orchestrator_draft`/`orchestrator_verify`
v1.yaml); `copilot.guardrails.policy` (`Role`); `copilot.guardrails.guardian` (`Guardian`,
`GuardianVerdict`); `copilot.guardrails.canary` (`canary_line`, appended to every system prompt
this module renders); `copilot.guardrails.audit_log` (`log_decision`, `log_approval`);
`copilot.guardrails.input_gate` (`InputGate`, Day 7 step 6 -- `answer()`'s very first call, with
`InputGate.record_spend` its last); `langgraph.checkpoint.base` (`BaseCheckpointSaver`, the
interface `checkpointer` is typed against); `langgraph.checkpoint.sqlite` (`SqliteSaver`, the
`checkpoint_path` fallback); `langgraph.types` (`Command`, `Send`, `interrupt`);
`langsmith.run_helpers` (`LangSmithExtra`).
Does not import `copilot.agents.specialists` directly -- tests inject fake executors, and the
real caller is `copilot.agents.wiring` (Day 6 step 7) via `scripts/run_orchestrator_golden.py`.

**29 Oct 2026: human approval fails closed.** `withhold_action` is a third hop between `guardian` and `END`: an Action draft the Guardian allowed, in an `Orchestrator` built without a checkpointer (so no approver could ever resume it), is held back instead of returned. The answer becomes `WITHHELD_ACTION_MESSAGE`, `approval_decision="withheld"`, and the hold is audit-logged. Before this, that case skipped approval silently.

### `src/copilot/agents/wiring.py` -- `build_executors()` *(day: 6, isNew: true)*
The one piece of glue nothing else needed: turns the five already-tested `run_*` functions
(step 2) into the `dict[AgentName, SpecialistExecutor]` shape `Orchestrator` takes, against real
services (`LLMClient`, `TextToSqlService`, a DuckDB connection, `CorrectiveRagService` + its
`PermissionedRetriever`) built the same way `scripts/run_effort_lab.py`/`run_rag_eval.py`
already build them -- this module doesn't reconstruct that wiring, it just closes over it.
`_inventory_executor(spec, con)` is the only non-trivial entry: `run_inventory_planning` needs a
`ForecastResult`, not a bare `TaskSpec` (step 2's own signature), so this calls
`forecast_result_for_inventory` itself first, keeping the executor map's own shape uniform.
**Takes in:** the already-constructed real services (see above), `con`/`policy` optional
(`None` falls back to each function's own default, same as calling it directly would).
**Gives out:** `dict[AgentName, SpecialistExecutor]`.
**Talks to:** `copilot.agents.contracts`/`orchestrator`/`specialists`; `copilot.guardrails.
policy`; `copilot.llm.client`; `copilot.rag.corrective`/`permissions`; `copilot.sql.service`.
Only caller so far: `scripts/run_orchestrator_golden.py`.

**31 Oct 2026:** `build_executors` passes the Action agent a lazily loaded vendor list (`_vendor_names_loader`) for its vendor lookup; no snapshot means no lookup, never a crash.

### `src/copilot/evals/orchestrator_golden.py`, `evals/datasets/orchestrator_golden_v1.jsonl` *(day: 6, isNew: true)*
Day 6 step 7's 10 multi-hop golden questions -- distinct from `copilot.evals.golden`'s
"multi_hop" category (gq-031..034), which is multi-step *SQL* answered by one specialist.
These are multi-*agent*-hop: each `OrchestratorGoldenQuestion` names `expected_agents`
(>=2, Pydantic-validated -- a single-agent question belongs in `golden`/`rag_golden` instead),
checked structurally (did the plan actually involve every specialist this question needs), not
by diffing against a fixed reference answer (no `expected_rows`/`reference_answer` field here --
see the module docstring for why grading multi-agent answer *content* is this step's stretch
goal, not its floor). Every question that expects `inventory_planning` also expects
`forecasting_risk`, per `orchestrator_plan`'s own planning rule -- `tests/
test_orchestrator_golden.py` asserts this stays true of the dataset itself.
**Gives out:** `OrchestratorGoldenQuestion`, `load_orchestrator_golden()`.
**Talks to:** `copilot.agents.contracts` (`AgentName`); `copilot.guardrails.policy` (`Role`).

**30 Oct 2026:** now loads `orchestrator_golden_v2.jsonl` (v1 + oq-011). Questions can carry `must_mention`, checked by `missing_mentions()`; the eval gate reports `orchestrator.answer_mentions_rate` (minimum 1.0).

### `prompts/orchestrator_plan/v1.yaml`, `prompts/orchestrator_draft/v1.yaml`, `prompts/orchestrator_verify/v1.yaml` *(day: 6, isNew: true)*
`orchestrator_plan`: lists the five specialists with one-line purposes (`_roster_block()` in
`orchestrator.py`), and states the one hard dependency the model must respect --
`inventory_planning` always implies planning `forecasting_risk` too, since the former needs the
latter's output. `orchestrator_draft`: given the question and every specialist's condensed
findings, writes the final answer, with the same "ground every number in what you were given"
rule `vendor_insight`/`text_to_sql` already use, plus the instruction to name (not resolve) any
conflict it notices between specialists; its `user_template` carries a `feedback_block` that is
the previous verifier feedback on a redraft, or a plain "no prior feedback" line on the first
pass (same posture as `model_selection_propose`'s own `feedback_block`). `orchestrator_verify`:
a second structured call -- same model family as the draft is fine here (unlike the Guardian's
cross-model-family posture, Day 7), since this catches drafting mistakes against known-good
inputs, not an adversarial safety check -- scoring `grounded`/`citations_ok`/`sufficient`/
`contradictions`/`feedback` strictly against the specialist findings and the draft's own
`cited_tasks`.

---

## Fine-tuning data, MCP server and QLoRA benchmark (Day 9)

*(Added 27 Oct, Day 10: these Day 9 files shipped without Code Map entries, breaking the
standing rule above; caught while preparing the end-of-sprint Code Map page and backfilled
here.)*

**30 Oct 2026: `orchestrator_draft/v2.yaml` and `orchestrator_verify/v2.yaml`.** Draft v2 must use units exactly as the findings state them and pass on every "WARNING:" line; verify v2 fails grounding for a wrong unit or a dropped warning. v1 files are unchanged (project rule: a changed rule is a new version).

**30 Oct 2026, later: `orchestrator_draft/v3.yaml` and `orchestrator_verify/v3.yaml`.** Ranking questions must use the measure the question names (checked against the "Sorted by:" line), and a definition or reason no finding states fails grounding.

**31 Oct 2026: `orchestrator_plan/v2.yaml`** requires `vendor_name` and `draft_type` on every action task.

**31 Oct 2026, later: `orchestrator_plan/v3`, `orchestrator_draft/v4`, `orchestrator_verify/v4`** make the level explicit: the plan must set it, the draft must not present portfolio figures as a vendor's, and the verifier fails a figure at the wrong level.

### `src/copilot/sql/pair_generation.py` -- `generate_candidates()`/`verify_and_filter()` *(day: 9, isNew: true)*
Builds the fine-tuning training set: question -> SQL pairs from a small family of templates,
filled with real vendor names and real columns, then kept only if they pass two counted filters:
(1) the SQL actually executes against the connected snapshot, and (2) it passes the same safety
validator production uses (`copilot.sql.validator.validate`). Vendor names are read from the
database at generation time and filtered to the k=5 disclosure threshold, never hardcoded
(ADR-002). Vendor filters are case-insensitive on the name exactly as the question shows it --
the v1 dataset compared stored casing against title-case question text, a rule the model could
not learn from its prompt, and that was fixed as v2.
**Takes in:** a live DuckDB connection and the vendor-name list.
**Gives out:** `Pair` objects and a `FilterReport` (candidates, execution failures, validator
failures, kept), plus per-category and per-table breakdowns.
**Talks to:** `copilot.sql.validator`, `copilot.data.store`; called by
`scripts/generate_sql_pairs.py`.

### `scripts/generate_sql_pairs.py` *(day: 9, isNew: true)*
CLI for the pair generator. Real run (22 Oct): 1016 candidates, 0 execution failures, 0
validator failures, sampled to 400 with a fixed seed.
**Takes in:** `--target` (default 400), `--seed` (default 42), `--out`; needs the built snapshot.
**Gives out:** `evals/datasets/sql_pairs_v2.jsonl` and its `.manifest.json` (count, by-category,
by-table, sha256).
**Talks to:** `copilot.sql.pair_generation`, `copilot.data.store`.

### `evals/datasets/sql_pairs_v1.jsonl`, `sql_pairs_v2.jsonl` (+ `.manifest.json` each) *(day: 9, isNew: true)*
The 400 execution-verified training/evaluation pairs. v1 is kept unchanged for history; v2 is
what the notebook trains on (340 train / 60 held-out). Each manifest stores a sha256 so a changed
dataset is detectable, the same pattern as the golden-set manifests.
**Takes in:** written by `scripts/generate_sql_pairs.py`.
**Gives out:** training and held-out data for `finetuning/`.
**Talks to:** `finetuning/day9_qlora_colab.ipynb`, `finetuning/eval_compare.py`.

### `src/copilot/mcp/server.py` -- `vendor_metrics`/`portfolio_summary`/`ask_vendor_question` *(day: 9, isNew: true)*
A read-only Model Context Protocol server (stdio transport) that gives any MCP host -- Claude
Desktop, the MCP Inspector, another agent -- three tools over the same guarded data path the
`/ask` API uses: one vendor's headline metrics, portfolio totals, and a free-form question that
runs through `TextToSqlService` and then the `Guardian`. Every tool is hard-wired to the lowest
role (`viewer`): a role passed in as a tool argument would be an unauthenticated claim and a
privilege-escalation route. Remote MCP with real authentication is a depth-track item.
**Takes in:** MCP tool calls (a vendor name, or a plain-English question).
**Gives out:** plain-text rows or a Guardian-reviewed answer; "not found" messages, never raw
errors.
**Talks to:** `copilot.data.store`, `copilot.sql.service.TextToSqlService`,
`copilot.guardrails.guardian`; tested by `tests/test_mcp_server.py`.

### `finetuning/day9_qlora_colab.ipynb` + `finetuning/requirements-colab.txt` *(day: 9, isNew: true)*
The Colab notebook that fine-tunes Qwen2.5-1.5B-Instruct with QLoRA on `sql_pairs_v2`'s 340
training pairs: 4-bit NF4 base weights, LoRA r=16 / alpha=32 / dropout=0.05, completion-only
loss, 3 epochs, free T4 GPU. `MAX_LEN` is 1024: at 512 every example's SQL answer was truncated
away, so the first adapter trained on nothing (loss 0.000000, every LoRA B matrix still zero).
GPU packages live in `requirements-colab.txt`, deliberately not in `pyproject.toml`.
**Takes in:** `evals/datasets/sql_pairs_v2.jsonl`.
**Gives out:** a saved LoRA adapter and `held_out.jsonl` (the 60 pairs it never trained on).
**Talks to:** `finetuning/eval_compare.py`.

### `finetuning/eval_compare.py` *(day: 9, isNew: true)*
Compares base zero-shot, base few-shot and the QLoRA adapter (and optionally the frontier API)
on the 60 held-out pairs by re-executing each generated query against the real snapshot and
comparing result rows, not SQL strings. Standalone (no `copilot` import) so it runs in Colab.
`few_shot_pool()` excludes held-out rows from the example pool -- without it, each test question
retrieved itself as its own top example. `_extract_sql()` takes only the SQL from a generation,
dropping trailing prose that had been glued onto correct queries. Real result (26 Oct): QLoRA
1.0 execution accuracy vs 0.017 zero-shot and 0.1 few-shot (ADR-007: adopt, conditionally).
**Takes in:** `--held-out`, `--adapter-dir`, `--snapshot-dir`, optional `--include-frontier`.
**Gives out:** a results table (execution accuracy, executable rate, mean latency per variant)
on stdout and as JSON.
**Talks to:** `snapshot.duckdb`; results recorded in `finetuning/results_template.md`.

### `finetuning/README.md`, `finetuning/results_template.md` *(day: 9, isNew: true)*
How to run the notebook and comparison script, why the GPU stack is kept out of the app, and
the full results table with the four bugs found and fixed before any number was trusted.

---

## Deploy and infrastructure (Day 2, Day 8)

### `docker/api.Dockerfile` *(day: 2)*
Production image for the API. Two stages: `uv` installs the locked dependencies in a builder,
and the runtime stage copies only the virtualenv and app code, runs as a non-root user, and
bakes the git SHA into `/version`.
**Takes in:** the repo plus `--build-arg GIT_SHA=...`.
**Gives out:** the `copilot-api` image (port 8000).
**Talks to:** built and smoke-tested by `.github/workflows/ci.yml`'s `image` job; run on EC2 by
`infra/server/deploy.sh`.

### `infra/server/user-data.sh`, `infra/server/deploy.sh` *(day: 2)*
`user-data.sh` bootstraps the Ubuntu EC2 host once (Docker + Compose, nginx reverse proxy to
127.0.0.1:8000, Certbot, AWS CLI). `deploy.sh` runs on the host via SSM Run Command, switches the
API to a new image and rolls back to the previous one if `/health` fails.
**Takes in:** `deploy.sh` takes the image URI and AWS region.
**Talks to:** `.github/workflows/ci.yml`'s `deploy` job; ADR-003.

### `infra/aws/github-oidc-trust.json`, `github-deploy-policy.json`, `ec2-instance-policy.json` *(day: 2)*
IAM documents: the trust policy that lets GitHub Actions assume a deploy role through OIDC (no
long-lived AWS keys in GitHub), the least-privilege deploy policy (push images to ECR, send SSM
Run Commands and read their results), and the instance policy (read and KMS-decrypt the app's
SSM parameters, nothing else).
**Talks to:** ADR-004; `.github/workflows/ci.yml`.

### `infra/local/compose.yaml` *(day: 8)*
Local-only Postgres container for exercising the Postgres checkpointer branch. See the scripts
table below.

### `tasks.ps1` *(day: 1)*
Windows PowerShell task runner: `setup`, `lint`, `typecheck`, `test`, `snapshot`, `check`.

---

## Living docs and portfolio pages (Day 1, Day 10)

### `docs/PROJECT_PROGRESS.md`, `BUILD_LOG.md`, `COMMANDS.md`, `TROUBLESHOOTING.md`, `RAID.md`, `TRADEOFF_LOG.md`, `HANDOFF.md`, `CODE_MAP.md` *(day: 1)*
The project's memory across chats: status per day, the dated build log (including every bug found
before a number was trusted), every command used, problems and fixes, the risk register, the
trade-off log, the hand-off note for the next chat, and this file. Not code; kept current in the
same commit as the change they describe.

### `evals/datasets/golden_v1.manifest.json`, `golden_v2.manifest.json` *(day: 1)*
File name, sha256, question count and per-category/per-split counts for each golden set, so an
edited golden set can't silently replace the one the results were measured on.

### `README.md` *(day: 10, isNew: true)*
The project front page: problem, architecture diagram, agent roster, results table (real numbers
only), cost and latency, ADR index, limitations, roadmap.

### `docs/DEMO_SCRIPT.md` *(day: 10, isNew: true)*
A timed 3-minute demo-video script (a real question, agents working, a Guardian block, a human
approval, the scoped QLoRA claim) with a recording checklist.

### `docs/CASE_STUDY.md` + `docs/case-study/index.html` *(day: 10, isNew: true)*
The case study for recruiters. The markdown is the source text; the HTML is the published page
(interactive agent graph, results ledger, bugs found in my own measurements), hosted as a shared
page until the domain exists, then moved there unchanged.

### `scripts/build_code_map_page.py` + `docs/code-map/template.html` -> `docs/code-map/index.html` *(day: 10, isNew: true)*
Builds the browsable Code Map page from this file. The page used to carry a hand-typed copy of
these entries, which had drifted five days behind; now the markdown is the only source and the
page is regenerated from it. Parses each `###` heading (path, symbol, day/isNew marker), its
description, and its Takes in / Gives out / Talks to lines; turns backticked file and
`copilot.*` module references in "Talks to" into links between entries.
**Takes in:** `docs/CODE_MAP.md` and the page shell `docs/code-map/template.html`.
**Gives out:** `docs/code-map/index.html` (published as the shared Code Map page).
**Talks to:** nothing at runtime; run `uv run python scripts/build_code_map_page.py` after
editing this file.

### `docs/tracker/index.html` *(day: 10, isNew: true)*
Source of the shared Progress Tracker page: the original long-range plan (phases, calendar,
costs) plus, from Day 10, a Sprint tab with every day's real outcome, the current RAID items
and the next steps. Edited by hand and republished to the same link.

### `docs/SPRINT_REPORT.md` *(day: 10, isNew: true)*
The final Daily Sprint Report: all ten days, what shipped and what didn't, metrics, costs, cuts,
open items, and the depth-track schedule.

---

## Not yet started (empty package markers only)
`src/copilot/dl/`, `src/copilot/nlp/`, `src/copilot/extract/`, `src/copilot/observability/`,
`src/copilot/ui/` — folders exist with an `__init__.py` so imports work later; no real code yet.
(`src/copilot/rag/`, `src/copilot/ml/`, `src/copilot/agents/` and, from Day 9,
`src/copilot/mcp/` have moved to the sections above. The UI that does exist lives in
`src/copilot/api/static/`.)

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
| `scripts/build_rag_index.py` | network (no API key) | downloads the embedding model, builds `data/chroma/` |
| `scripts/train_risk_classifier.py` | your real `vw_PortfolioHealth` export (CSV/XLSX) | real RF/XGBoost leaky-vs-safe accuracy/F1 + SHAP drivers, appends to `run_log.csv` |
| `scripts/run_model_selection_eval.py` | `ANTHROPIC_API_KEY` (every run, not just `--quality`) | real Model Selection Agent runs over the 8-question golden set; `--quality` adds the LLM-judged reasoning check |
| `scripts/run_orchestrator_golden.py` | `ANTHROPIC_API_KEY` + the real snapshot + `data/chroma/` | Day 6 step 7: runs the 10 multi-hop golden questions end to end through the real Orchestrator (real specialists, real Verifier loop); prints plan coverage, verified status, cost/latency per question, and leaves a SQLite checkpoint per run at `data/orchestrator_checkpoints.sqlite` |
| `scripts/generate_sql_pairs.py` | the snapshot | Day 9: writes the 400 execution-verified question -> SQL pairs (`sql_pairs_v2.jsonl` + manifest) |
| `finetuning/day9_qlora_colab.ipynb` then `finetuning/eval_compare.py` | Google Colab, free T4 GPU, `snapshot.duckdb` uploaded | Day 9: QLoRA fine-tune, then base vs few-shot vs QLoRA on the 60 held-out pairs |
| `docker compose -f infra/local/compose.yaml up -d` | Docker | Day 8 step 7: a local-only Postgres container for exercising `copilot.api.dependencies._build_checkpointer`'s Postgres branch for real; set `CHECKPOINT_DATABASE_URL` in `.env` to the printed connection string, nothing else changes |

## Tests (`tests/*.py`)
One test file per module above, named `test_<module>.py` — not documented individually here since
they mirror the module list exactly. `tests/fakes/anthropic_fakes.py` is a fake Anthropic SDK used
so `test_llm_client.py` and others can test retry/repair/caching logic without a real API key.
`tests/conftest.py` (Day 7 step 6) is an autouse fixture that points every test's default
`InputGate` spend tracking at a throwaway `tmp_path` file instead of the real repo path --
without it, every orchestrator test that builds a plain `Orchestrator(...)` with no explicit
`input_gate` would share one on-disk running total across the whole test session.
`tests/test_privacy_leakage_suite.py` (Day 7 step 8) is the one exception to "mirrors the module
list" -- it's a cross-cutting suite, not a per-module test file: 23 named cases (15 role-
escalation/poisoned-contract/cross-vendor-draft/prompt-extraction/etc. cases through `Guardian`/
`InputGate`, + 8 SQL red-team cases from `docs/specs/text_to_sql_safety.md` through the
validator), each asserting the real outcome a leak attempt gets today, run as ordinary pytest
(no separate eval harness) so a regression here fails CI the same way any other test would.
