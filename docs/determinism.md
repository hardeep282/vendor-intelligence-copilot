# A note on determinism

Day 8, Addendum A2 §1.7. Short by design -- A2 calls for a doc paragraph, not a new mechanism;
everything below describes what's already shipped, dated to when.

**What is deterministic in this system, and always has been:** the Guardian's 8 checks
(ADR-006), the input gate (kill switch, length, injection heuristics, scope, rate limit, spend
cap -- Day 7 step 6), the SQL validator (Day 3-7, `sqlglot`-based AST inspection, no LLM call),
the auth/rate-limit layer (Day 8 steps 4-5), and `copilot.evals.evaluators.execution_accuracy`/
`leakage_free` (Day 3-7: exact row-value comparison with a fixed 0.01 numeric tolerance, SQL
re-validation against the same `validate()` the service itself calls). None of these ever
touch an LLM; given the same input and the same code, they give the same output, every time,
on any machine.

**What is not, and cannot be, deterministic:** anything that calls `LLMClient.complete()`/
`.structured()` -- planning, drafting, verifying, every specialist's own reasoning, the
RAG/Model-Selection LLM judges. This project does not try to force determinism onto that layer
(no `seed` parameter exists on this model generation's Messages API, same `temperature`/`top_p`/
`top_k` removal `copilot.llm.client`'s own module docstring already documents -- there is
nothing to pin even if we wanted to), and does not claim bit-for-bit reproducibility anywhere an
LLM call sits on the path. Instead, each layer narrows how much that variance can actually
matter to the final answer:

- **Forced structured output** (`output_format=<PydanticModel>`, every call site, Day 3
  onward) bounds variance to the content of typed fields, never free-form shape -- a draft
  answer's *wording* can vary call to call; `DraftAnswer.cited_tasks` either names the right
  task or it doesn't, and the Verifier's `grounded`/`citations_ok`/`sufficient` booleans are
  still exact pass/fail checks against that content, not a vibe.
- **The repair loop** (`structured()`'s own retry-on-validation-failure, Day 3) and **the
  Verifier's redraft loop** (Day 6 step 4, capped at `MAX_VERIFICATION_LOOPS`) both exist
  because the *first* sampled output is not guaranteed correct -- the system is built to notice
  and correct a bad sample, not to prevent sampling variance from happening in the first place.
- **The Guardian runs after every draft, unconditionally** (Day 7 step 4, the one path to
  `END`) -- whatever variance produced the draft, the thing a caller actually receives has
  already passed the same deterministic checks every other draft has, every time.
- **Golden-set evals tolerate exactly the variance that's expected and nothing more**:
  `NUMERIC_TOLERANCE = 0.01` (rounding, not reasoning drift), binary 1.0/0.0 scores (no partial
  credit that could hide a real miss as "mostly fine"), and the CI eval gate's own thresholds
  (`evals/thresholds.yaml`, Day 8 step 6) are rates across a whole golden set, not a pass/fail
  on any single sampled run -- a gate that demanded 100% on an inherently sampled process would
  be measuring luck, not quality.
- **Prompt version pinning** (A2 §1.5, Day 8 step 1/2: `CallMetrics.prompt_name`/
  `.prompt_version` on every trace) doesn't make a given prompt version's *output*
  deterministic, but it does make every trace attributable to an exact, reviewable prompt
  file -- so a quality shift shows up as "version 2 of `orchestrator_draft` behaves differently
  from version 1," a deterministic fact about the system's configuration, not an untraceable
  shrug.

**The practical upshot, stated plainly:** this system is deterministic exactly where it should
be -- every safety, access-control, and validation decision -- and openly non-deterministic
exactly where an LLM call is doing real reasoning work, with every mechanism above built to
catch a bad sample from that non-determinism before it reaches a caller, rather than pretending
the non-determinism isn't there.
