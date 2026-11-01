# ADR-006: Guardian Design — outcome severity, escalation, scope, and detection posture

**Status:** Accepted — 21 Oct 2026.

## Context

Day 7 built `Guardian.review()`: 8 deterministic checks (canary leak, restricted-table-name leak, raw-row-shape, role policy, vendor-facing-audience, secrets, PII, grounding) run cheapest-first against every agent result, producing one of four outcomes — ALLOW / REDACT / BLOCK / ESCALATE. The code shipped with working defaults (440/440 tests passing), stated in the code's own docstrings as proposals, not settled decisions. Per Addendum A1, the real architectural calls needed the user's own answers, not Claude's. Answered 21 Oct 2026.

## Questions and answers

### 1. Outcome severity ordering

**Answer:** Agreed with the shipped default. When multiple checks fire on the same result, the worst-severity finding decides the outcome, in this order (worst to least severe): **BLOCK > ESCALATE > REDACT > ALLOW**. A blocked leak is never downgraded just because a milder issue was also found in the same result.

### 2. ESCALATE-with-no-reviewer-yet behaviour

**Answer:** An escalated result should be shown with a **visible "pending review" status**, not hidden — so that whoever looks at it (a future reviewer, or the user checking the audit log today) can see what the outcome was and where it currently stands, rather than the answer silently disappearing.

**This is a deliberate deviation from what Day 7 actually shipped**, which withholds an escalated result entirely until manually released via the log. **Required Day 8 task, scheduled now, not deferred:** there is currently no UI surfacing a "pending review" status anywhere — only the gitignored `data/audit/guardian_log.jsonl` file. Making ESCALATE visible as decided here requires (a) the orchestrator/API layer returning a structured "pending review" state instead of withholding the result, and (b) Day 8's UI work rendering that state to the user. This is to be built as part of Day 8 itself — specifically alongside the `/ask` endpoint and UI work already on Day 8's list — not left as an optional later cleanup, since otherwise this ADR's decision and the shipped code would keep disagreeing indefinitely.

### 3. Vendor-audience check scope

**Answer:** The current scope is fine as the Day 7 minimum — the check only needs to fire when an Action draft is bundled together with another specialist's non-public data. No wider check (e.g. a plain knowledge-agent answer alone, with no Action draft, going to a vendor-facing channel) is needed right now.

### 4. Raw-row-shape detection approach

**Answer:** The pattern-based heuristic (`RAW_ROW_PATTERN`: 10+ consecutive delimited lines) is acceptable as the Day 7 minimum, but it's a known limitation, not the long-term design. The real fix — tying the check to actual SQL/data-class provenance (what was actually queried) rather than pattern-matching the rendered text — belongs in the post-sprint depth pass, alongside the other deferred RAG items (MMR, the LangGraph/LangChain adapter layer, HyDE, Self-RAG).

## Decision

Guardian's severity ordering (BLOCK > ESCALATE > REDACT > ALLOW) and its vendor-audience and raw-row-shape check scopes are confirmed as-shipped for Day 7 and need no code change. ESCALATE's *intended* behaviour changes from "withhold until manually released" to "show as visibly pending review" — this is a scope decision only; the code to implement it does not exist yet.

## Consequences

- No code changes required for questions 1, 3, 4 — Day 7's shipped behaviour already matches the decision.
- Question 2 opens a real, named gap: Guardian's current code does not implement "visible pending review." This is scheduled as a required part of Day 8 (alongside the `/ask` endpoint and UI work), not left open-ended — until it's built, an ESCALATE result continues to behave exactly as Day 7 built it (withheld, logged only).
- Raw-row-shape detection is explicitly logged as a known limitation to revisit in the post-sprint depth pass, not a silent gap.
- Vendor-audience scope stays narrow by design; if this copilot later gains a vendor-facing read channel without an Action draft in the loop, this decision should be revisited rather than assumed to still hold.

## Implementation note (Day 8)

Implemented in `copilot.api.main` (`/ask`'s SSE stream emits a `pending_review` event instead of withholding) and `copilot.agents.orchestrator` (`OrchestratorResult` gains a `pending_review: PendingReview | None` field carrying the Guardian reason code and audit-log entry id, set instead of raising/withholding when the Guardian outcome is ESCALATE). See `docs/CODE_MAP.md` for the exact surface.

## Amendment (2 Nov 2026): the audience check applies only to drafts a vendor will read

**What happened.** In the first full 11-question real-key golden run, oq-008 asked for "the reorder point for our top vendor by revenue, and a reorder recommendation reflecting it". The Guardian blocked the answer with `vendor_audience_violation`. Question 3's scope fired on any Action draft, and this draft was built on our own internal forecast. A reorder recommendation, though, goes to our own procurement/inventory team, not to the vendor. The `action_draft` prompt already said so ("the reader is internal ... internal figures are fine to include"). So the block protected nobody and stopped a legitimate internal answer.

**Decision (the user's, 2 Nov 2026).** The vendor-audience check now applies only to Action drafts a vendor will read.
- `policies/disclosure.yaml` (now version 2) lists the internal draft types under `vendor_facing_audience.internal_draft_types`. Today that list is `[reorder_recommendation]`.
- A draft whose type is on that list is not held to the vendor-audience rule.
- Every other draft type is held to it. That includes `renegotiation_email`, any type added later, and a draft with no recorded type. The default fails closed.
- The draft type is read from the Action result's own evidence (`draft_type=...`), which `run_action` writes.

**What does not change.**
- The role rules still apply to internal drafts: a viewer still can't receive confidential figures through one.
- Every other Guardian check still runs: canary, restricted names, raw rows, secrets, PII, grounding.
- The human approval gate still applies to every Action draft, internal or not.
- A renegotiation email built alongside internal data is still blocked. That's oq-005 in the golden set and cases 9 and 10 in the privacy leakage suite.

**Limit, stated honestly.** The check still trusts the draft type the Action specialist recorded. If a draft labelled `reorder_recommendation` were later sent to a vendor, this check would not catch it. The approval gate is the control for that. An approver should treat any draft leaving the company as vendor-facing, whatever its label. This amendment narrows question 3's scope; it doesn't change the severity ordering or questions 1, 2 and 4.

Tests: `tests/test_guardian.py`, the four `draft_type` tests added 2 Nov 2026.
