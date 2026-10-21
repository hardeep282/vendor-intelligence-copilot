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
Day 7 step 6 added the input gate's knobs: `daily_spend_cap_usd` (already present, now actually
enforced), `rate_limit_per_minute` (default 30), `max_question_chars` (default 4000),
`kill_switch_enabled` (default `False` — the one flag an operator flips first in an incident).
Day 8, A2 §1.1 added `fallback_model` (default `None` — no fallback, so a primary-model outage
still surfaces as an error exactly as before this existed; an operational choice, left unset in
`.env.example` on purpose since ADR-005 already names the primary).
**Takes in:** environment variables, plus a local `.env` file (never committed).
**Gives out:** a cached `Settings` object via `get_settings()`.
**Talks to:** everything else that needs a key or a path — `LLMClient`, all the `scripts/*.py`,
`copilot.data.store`, `copilot.guardrails.input_gate` (Day 7). This is the *only* code that reads
`.env` directly; anything that builds its own API client (e.g. `anthropic.Anthropic()`) must go
through this, or it won't see the key.

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

### `src/copilot/guardrails/policy.py`
Parses `policies/disclosure.yaml` into typed objects and answers "may this role see this?".
**Takes in:** the YAML policy file.
**Gives out:** a validated `DisclosurePolicy`.
**Talks to:** `TextToSqlService` (schema linking + validator), `InsightService` (k-threshold
masking), `copilot.guardrails.guardian`/`canary` (Day 7: role-policy/vendor-audience checks and
the canary-token prefix both read this same policy object).

### `policies/disclosure.yaml` / `policies/sql_rules.yaml`
Data, not code: which roles may see which tables/columns (disclosure), and the structural/semantic
rules the SQL validator enforces (sql_rules). Changing a rule is a diff to these files, not Python.

---

## LLM layer — the one place every model call goes through

### `src/copilot/llm/client.py` — `LLMClient`
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
call path produced it. Holds `CallMetrics` (TTFT, latency, tokens, cost). Day 8, A2 §1.1/§1.5:
`CallMetrics` also carries `prompt_name`/`prompt_version` (which versioned prompt file produced
this call, if any) and `used_fallback_model` (whether `LLMClient._with_fallback()` actually had
to fail over — tells "fallback succeeded" apart from "primary succeeded on the first try").

---

## SQL layer — turning a question into a safe query

### `src/copilot/sql/service.py` — `TextToSqlService`
One business question → one validated DuckDB query → real rows. Shows the model only its role's
tables (schema linking) and 3 similar verified examples, validates every candidate query through
all 6 validator layers before running it, and on rejection feeds the exact violations back to the
model as the next turn (self-correction, max 2 retries) rather than giving up or running bad SQL.
Day 7 step 2: its system prompt now appends `canary_line("data_analyst")`.
**Talks to:** `schema.py`, `examples.py`, `validator.py`, `store.py`, `LLMClient`,
`copilot.guardrails.canary` (Day 7).

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

### `src/copilot/api/main.py`
The FastAPI HTTP entry point. Day 2 walking skeleton: `/health` says the process is alive,
`/version` says exactly which build is deployed. `/ask` (behind auth) comes later.

---

## RAG / Knowledge layer — the Knowledge agent's retrieval stack (Day 4)

### `knowledge/*.md`, `knowledge/contracts/*.md`
The RAG source corpus, not code: 4 methodology-family docs (data dictionary, metric definitions,
decision log, methodology — `public`/`internal`) + 10 synthetic vendor supply-agreement summaries
(`confidential`), each headed `SYNTHETIC` and stating no real contract exists. Every doc opens with
YAML frontmatter (`doc_type`, `vendor`, `version`, `data_class`, `allowed_roles`).
**Talks to:** `copilot.rag.corpus` is the only code that reads these.

### `src/copilot/rag/corpus.py`
Parses every knowledge doc's frontmatter + Markdown body into a typed `KnowledgeDoc`.
`check_corpus_against_policy()` recomputes each doc's expected `allowed_roles` from the live
disclosure policy and fails loudly if a doc's hand-authored roles have drifted from it.
**Takes in:** the `knowledge/` directory.
**Gives out:** `list[KnowledgeDoc]`.
**Talks to:** `copilot.guardrails.policy` for `DataClass`/`Role` and the drift check;
`copilot.rag.chunking` reads its output.

### `src/copilot/rag/chunking.py`
Splits each `KnowledgeDoc`'s body into `Chunk`s at every Markdown heading (the real semantic
boundaries in this hand-curated corpus), re-splitting by paragraph (with overlap) only if one
section runs over ~1000 chars — comfortably under the embedder's truncation point. Carries the
doc's permission metadata (`data_class`, `allowed_roles`) onto every chunk.
**Takes in:** `list[KnowledgeDoc]`.
**Gives out:** `list[Chunk]`, each with a stable `chunk_id` and a `content_hash` of its text.
**Talks to:** `copilot.rag.store` reads its output; `copilot.rag.corpus` for the input type.

### `src/copilot/rag/embeddings.py`
`Embedder` protocol + `SentenceTransformerEmbedder` (local `all-MiniLM-L6-v2`, 384-dim, lazy-loaded
so constructing it never triggers a download) + `FakeEmbedder` (deterministic, no network — used by
every test in this repo). The real model's weights come from the Hugging Face Hub, which this build
sandbox's proxy blocks, so the real embedding run is `scripts/build_rag_index.py` on your machine.
**Takes in:** chunk text (or a query string).
**Gives out:** one float vector per text.
**Talks to:** `copilot.rag.store.ChunkStore.upsert`/future retrieval code call `embed()`.

### `src/copilot/rag/store.py`
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

### `src/copilot/rag/retrieval.py`
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

### `src/copilot/rag/permissions.py`
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

### `src/copilot/rag/corrective.py`
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

### `scripts/build_rag_index.py`
Loads the corpus, checks it against the live disclosure policy, chunks it, embeds with the real
local model, and upserts into `data/chroma/` — prints how many chunks were actually (re-)embedded
vs. already up to date.
**Needs:** nothing but normal internet access (no API key — the model is local and free to run).
**Talks to:** every `copilot.rag.*` module above, in pipeline order.

### `scripts/run_rag_eval.py`
Day 4 step 7's eval runner. Retrieval metrics (recall@k, MRR — `copilot.evals.rag_metrics`) are
free and run against whatever's already in `data/chroma/`. `--quality` additionally runs the
cut-down Ragas pair (`copilot.evals.rag_quality`: faithfulness + context_recall) via real
`CorrectiveRagService`/LLM calls — costs money, off by default.
**Needs:** the real Chroma index (`build_rag_index.py` first); `--quality` needs `ANTHROPIC_API_KEY`.
**Talks to:** `copilot.evals.rag_golden`/`rag_metrics`/`rag_quality`, `copilot.rag.permissions`,
`copilot.rag.corrective`.

### `src/copilot/evals/rag_golden.py`, `rag_metrics.py`, `rag_quality.py`
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

### `src/copilot/ml/metrics.py`
WAPE, MASE, bias -- the three forecast-accuracy metrics the sprint doc names (not MAPE, which
the analytics repo's own `forecast_backtest.py` already found unreliable near-zero actuals).
**Takes in:** parallel actual/forecast sequences (plus the training series, for MASE's scale).
**Gives out:** one float per metric.
**Talks to:** nothing -- pure NumPy arithmetic, no fakes needed, same category as
`copilot.evals.rag_metrics`.

### `src/copilot/ml/forecast.py` — `forecast_demand()`
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

### `src/copilot/ml/inventory.py` — `compute_inventory_plan()`
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

### `src/copilot/agents/model_selection.py` — `ModelSelectionAgent`
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

### `src/copilot/evals/model_selection_golden.py`, `model_selection_metrics.py`, `model_selection_quality.py`
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

## Multi-agent system -- Orchestrator + 5 specialists (Day 6, in progress)

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
**Takes in:** an `LLMClient`, `executors: dict[AgentName, SpecialistExecutor]` -- the Day 6
step 2 `run_*` functions, wired in by the caller (never constructed here: each needs a
different real dependency the Orchestrator has no business reproducing) -- plus a question,
`Role`, and optional `thread_id` at call time; optional `checkpoint_path`/`guardian` at
construction time. `resume_approval` additionally takes `thread_id`, a decision
(`"approve"|"edit"|"reject"`), the approver's `Role`, and an optional `edited_answer`.
**Gives out:** `OrchestratorResult` (plan, every `AgentResult`, the drafted answer,
`conflicts_noted`, `verified`/`verify_attempts`, summed cost/latency/llm_calls across plan +
every specialist + every draft/verify attempt, `guardian_verdict`, `pending_approval`,
`approval_decision`).
**Talks to:** `copilot.agents.contracts` (`TaskSpec`/`AgentResult`/`AgentBudget`/`AgentName`);
`copilot.llm.client`/`prompts` (`orchestrator_plan`/`orchestrator_draft`/`orchestrator_verify`
v1.yaml); `copilot.guardrails.policy` (`Role`); `copilot.guardrails.guardian` (`Guardian`,
`GuardianVerdict`); `copilot.guardrails.canary` (`canary_line`, appended to every system prompt
this module renders); `copilot.guardrails.audit_log` (`log_decision`, `log_approval`);
`copilot.guardrails.input_gate` (`InputGate`, Day 7 step 6 -- `answer()`'s very first call, with
`InputGate.record_spend` its last); `langgraph.checkpoint.sqlite` (`SqliteSaver`);
`langgraph.types` (`Command`, `Send`, `interrupt`); `langsmith.run_helpers` (`LangSmithExtra`).
Does not import `copilot.agents.specialists` directly -- tests inject fake executors, and the
real caller is `copilot.agents.wiring` (Day 6 step 7) via `scripts/run_orchestrator_golden.py`.

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

## Not yet started (empty package markers only)
`src/copilot/dl/`, `src/copilot/mcp/`, `src/copilot/nlp/`, `src/copilot/extract/`,
`src/copilot/observability/`, `src/copilot/ui/` — folders exist with an `__init__.py` so
imports work later; no real code yet. (`src/copilot/rag/`, `src/copilot/ml/`, and
`src/copilot/agents/` have moved to the sections above.)

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
