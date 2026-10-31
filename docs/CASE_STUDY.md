# Case study: Vendor Intelligence Copilot

*Source text for the case-study page. Published 27 Oct 2026 as a hosted page
(https://claude.ai/artifact/KyLyQ3ywwWjWuXEvKKR1YF, built from `docs/case-study/index.html`)
until the domain and landing page exist (Day 2 scope, still pending); the same HTML moves to
the domain unchanged once it does. Edit the text here first, then the HTML.*

---

## The problem

A beverage distributor's category, procurement and finance teams need to answer commercial
questions that span several data sources at once: which vendors are leaking controllable
margin, what next quarter's demand looks like, and what to renegotiate.
Getting that from a 12.8-million-row SQL medallion by hand is slow. Handing it to an LLM
directly is worse — a single agent answering unverified is a liability when the answer touches
real vendor contracts and real margin figures.

## The approach

I built a multi-agent system where the architecture itself is the guardrail, not a prompt:

- **Python computes every number.** Forecasts, risk scores, safety-stock calculations — all
  deterministic tools. The LLM narrates; it never invents a figure.
- **Five specialist agents, least privilege.** A Data Analyst (text-to-SQL), a
  Forecasting & Risk agent, an Inventory Planning agent, a Knowledge agent (retrieval over
  methodology and contract documents), and an Action agent that only drafts — never sends.
  Each works in its own lane with its own tools; none can call another's tools directly.
- **A Verifier checks the draft is actually grounded** in what the specialists found before it
  goes anywhere near the user — up to two redraft loops, then finalized honestly flagged if it
  still isn't confirmed.
- **A Guardian is the one mandatory gate every single answer passes through.** Eight checks,
  worst-severity-wins, before anything reaches the user: canary-token leaks, restricted-table
  names, raw-row dumps, role-based policy, a vendor-facing audience check (a renegotiation email
  to vendor X can never carry another vendor's terms or our internal margins), secrets, PII, and
  whether the Verifier actually confirmed grounding. This isn't a convention — it's a test
  asserted against the compiled agent graph's own edges, not against the code that built it.
- **Anything that leaves the system stops for a human.** Action drafts pause on a real
  interrupt; an approver approves, edits or rejects before anything is finalized.

## The results

Nothing below is a projection — it's a real number from a real run, or explicitly marked as
still pending a credential or a local run I haven't done yet:

- **539 automated tests passing, 0 failing.**
- **23/23 on a privacy red team** — 15 data-leakage attack patterns plus 8 SQL-injection
  attempts (UNION into uncatalogued tables, file reads via table functions, unbounded
  denial-of-service joins), all correctly blocked or escalated.
- **A 6-layer SQL safety validator** catches semantically-wrong-but-syntactically-valid SQL
  (averaging a margin percentage instead of weighting it, a join that silently fans out and
  inflates a total) before it ever reaches a user — 0 false positives across 33 real queries.
- **Real retrieval quality:** recall@5 = 0.800, MRR = 0.662 on a hybrid BM25 + vector search
  with reciprocal rank fusion, measured against a labelled question set, not assumed.
- **A SKU risk classifier validated on 10,495 real SKUs** after finding and fixing a genuine
  data-leakage bug (a feature that algebraically reconstructed the target column) — F1 dropped
  honestly from 0.994 to 0.919 once the leak was removed, which is the real, trustworthy number.
- **A QLoRA fine-tune of a small open model for text-to-SQL, benchmarked**: 1.0 execution
  accuracy against a 1.7% zero-shot baseline, at a mean latency between the zero-shot and
  few-shot baselines (4.4 s vs 6.8 s and 3.8 s). I scoped the claim
  honestly in the write-up (ADR-007): proven within a fixed question template, not general
  text-to-SQL, and not yet wired into the production path pending a broader validation set.

## What I'd do next

Validate the fine-tune against question phrasings outside its training template before
considering it for production; finish deployment (AWS, domain, live demo link); run the
real-key evaluation suite end to end (currently built, tested, and ready, pending credentials
and local GPU/browser sessions I run outside this build environment); then deepen retrieval
(reranking, GraphRAG experiment), harden the Postgres checkpointer against a live database, and
build out the Model Selection Agent's real evaluation numbers.

Full build history, every bug found and fixed before a number was trusted, and every
architecture decision with its reasoning: [GitHub
repo](https://github.com/hardeep282/vendor-intelligence-copilot).
