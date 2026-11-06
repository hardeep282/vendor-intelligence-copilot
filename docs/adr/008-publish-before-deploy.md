# ADR-008: Publish the repository and case study before the system is deployed

**Status:** Accepted, recorded after the fact. The repo went public on 28 Oct 2026; this record
was written on 6 Nov 2026 from the owner's answers to the four Day 10 questions.

## Context

At the end of the 10-day sprint, the copilot ran on my laptop but had no live link. The AWS
deployment is written (Dockerfile, CI deploy job, server scripts, OIDC policies) but isn't
switched on, and I have no domain yet. The choice was between waiting until it was deployed
before showing it to anyone, and publishing the code, the build log and a case-study page now.

Two open items in `docs/RAID.md` bore on this:
- **R1:** is the purchased dataset allowed to appear in public?
- **R7:** vendor names appear in the golden sets and the snapshot.

## Decision

Publish now. Make the repo public, share the case-study page, and deploy afterwards.

1. **Why not wait for a live link.** A recruiter loses the chance to click and try it. In
   exchange, they can read the code, the 596 tests, the decision records and a day-by-day build
   log today, rather than weeks from now. For an analytics and AI candidate, how the work was
   reasoned and checked matters more than a running demo, and the real-key results (11
   multi-step questions, 10 verified, $0.48 in total) show that it runs.
2. **The data question (R1, R7).** I've confirmed that the dataset can be used for this work.
   The original data is kept out of the repo for a practical reason: it's far too large for
   GitHub. So the existing design stays exactly as it is (ADR-002):
   - only vendor-level aggregates go into the snapshot;
   - the snapshot is git-ignored, with only its manifest tracked;
   - a guard refuses row-level tables.

   Vendor names such as Diageo are real public companies and are already in the public README.
   **R1 and R7 are closed by this decision.**
3. **Where the case study lives.** It stays on its shared claude.ai link for now, and that is
   the link on my CV. A domain and my own website come later. When they do, the case study moves
   there, and the CV link changes in the same update.
4. **The claims an interviewer will probe.** Every claim on the public pages needs an
   explanation I can give in my own words: the concept, the code behind it, and its limits. The
   claims most likely to be pushed on, and how each is stated publicly:
   - **QLoRA fine-tune "1.0 execution accuracy":** true only within a fixed family of question
     templates; benchmarked, not deployed (ADR-007).
   - **The forecast tie:** with only 12 months of history, ETS can't learn seasonality and its
     trend comes out close to nothing, so it ties with the naive baseline (WAPE 0.1153). This is
     reported as it came out.
   - **Risk-classifier F1 0.919:** measured on 10,495 real products after removing a feature
     that leaked the label. The first score of 0.994 was a bug, not a result.
   - **"Verified":** the answer passed an AI fact-check against the specialists' findings. It
     does not mean independently audited; the build log records verified answers that were still
     wrong, and the fixes that followed.
   - **Latency:** a median of 17 s and a range of 10–52 s per question, from real runs. There's
     no per-step p95 table yet.

## Consequences

- **Built with an AI pair programmer, under my direction.** I set the goals, the constraints and
  the standards, and reviewed each step; the commits are co-authored with Claude. So
  understanding every component is a release requirement for me, not an extra. Before the demo
  video or any interview, I work through each layer (data and SQL, ML, RAG, the LLM layer,
  agents, guardrails, product and CI) until I can explain its concepts, its code and its limits.
- **Deploy next, on the AWS address, until a domain exists.** Without a domain there's no HTTPS
  certificate, so keys would travel unencrypted. The deploy session has to settle how the live
  link is protected before it's shared.
- **ADR-002's reason changes, its rule doesn't.** ADR-002 assumed the data couldn't be shared.
  With the licence confirmed, aggregate-only and never-committed stay in place, now for size and
  least-privilege reasons.
- **What would reverse this:** any sign that the dataset's terms don't allow this use. In that
  case, the vendor-level figures and names would come out of the public pages, and the other
  analytics repo would be checked too.
