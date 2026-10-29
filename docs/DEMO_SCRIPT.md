# 3-minute demo video script

Record against `uv run uvicorn copilot.api.main:app` running locally
(`http://localhost:8000/`), screen + voiceover. Every number below is real, pulled from
`docs/PROJECT_PROGRESS.md` — do not improvise different figures on camera.

## 0:00–0:20 — Open on the problem, not the UI

> "This is the Vendor Intelligence Copilot — a decision-support system for a beverage
> distributor's procurement team, built on a real 12.8-million-row SQL medallion. The question
> it answers: which vendors are leaking controllable margin, why, and what should we do about
> it — without a hallucinated number or a leaked confidential field reaching the user."

Show the architecture diagram from the README (or the Mermaid render) for 3–4 seconds while
saying this.

## 0:20–1:10 — A real question, agents working

Type a real question into the UI, e.g.:
*"Which vendors are leaking the most controllable margin, and what's the portfolio demand
forecast for next quarter?"*

Ask at **vendor and portfolio level only**. The snapshot holds no SKU-level rows (ADR-002), so a
"top SKUs" question makes the Data Analyst correctly report that it can't answer, the Verifier
can't confirm the draft, and the Guardian escalates it. That happened in the first real UI run on
29 Oct 2026 (see `docs/BUILD_LOG.md`), which is why the question changed.

As the agent-status strip updates live (`StreamEvent(type="node")`), narrate each node by name
as it lights up:

> "The input gate checks this isn't an injection attempt before anything else runs. The
> Orchestrator plans and fans the Data Analyst and Forecasting & Risk specialists out in
> parallel — that's LangGraph's `Send` API, not a sequential chain. Each specialist only touches
> its own tools: the Data Analyst runs text-to-SQL through a 6-layer validator, Forecasting runs
> a real ETS-vs-naive backtest, never an LLM guess."

Let the draft + citations render. Point at one cited figure and say where it came from
(a real tool call, not the model's memory).

## 1:10–1:45 — A Guardian block, on camera

Pre-stage a question designed to trip a real Guardian check — e.g. ask for another vendor's
contract terms inside an Action draft, or ask a scope-check question the input gate rejects.
Show the actual BLOCK/ESCALATE response with its reason code.

> "This is the part that makes the architecture the guardrail, not a prompt. Every single path
> in this graph passes through the Guardian before the user sees it — that's not a convention,
> it's a test (`test_every_path_to_end_passes_through_guardian`) asserted against the compiled
> graph's own edges. Worst-severity-wins across 8 checks: canary-token leaks, restricted table
> names, raw-row dumps, role policy, a vendor-facing audience check, secrets, PII, and whether
> the Verifier actually confirmed the draft is grounded."

## 1:45–2:25 — A human approval

Ask for an Action draft (a renegotiation email or reorder recommendation). Show it pause on the
interrupt, then approve it through `/ask/approve` as the `approver` role.

> "Anything that leaves the system — an email draft, a reorder recommendation — stops here for a
> human to approve, edit or reject. Nothing is ever sent automatically."

## 2:25–2:50 — The honest part

> "This is benchmarked, not oversold. I fine-tuned a small open model with QLoRA for
> text-to-SQL and it hit 1.0 execution accuracy against a 1.7% baseline — but that's proven
> within a fixed question template, not general text-to-SQL, and it's not wired into production
> yet — that's the actual decision I wrote down in ADR-007, not a claim I'm making on a CV."

## 2:50–3:00 — Close

> "Over 500 tests passing, a 23-case privacy red team at zero leaks, real numbers on every claim in
> the README. Full write-up and every decision I made along the way is in the repo."

Show the GitHub repo URL and the README on screen for the last 3 seconds.

---

## Recording checklist

- [ ] Server running locally with `ANTHROPIC_API_KEY` set (a real-key run — see
      `docs/PROJECT_PROGRESS.md`'s "Next step" for which scripts still need this)
- [ ] One happy-path question rehearsed once before recording (know what it returns)
- [ ] One Guardian-block question rehearsed and confirmed to actually trip a real check
- [ ] One Action-draft + approval flow rehearsed through `/ask/approve`
- [ ] Screen resolution clean (hide other tabs/notifications)
- [ ] Upload unlisted on YouTube or host on the domain once it exists; link from the README and
      the case-study page
