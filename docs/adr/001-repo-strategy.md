# ADR-001: Separate repository, linked from the analytics repo

Date: 2026-10-10 · Status: Accepted

## Context
The analytics project is a finished portfolio piece. The Copilot adds services, infrastructure and deployment.

## Options
1. Add the Copilot to the analytics repo.
2. New repo `vendor-intelligence-copilot` that consumes a licence-safe snapshot of the analytics outputs.

## Decision
Option 2. Infrastructure code lives in `infra/` in the new repo. The analytics README links to it.

## Consequences
The analytics repo stays reviewable on its own. The data hand-off is an explicit, tested contract (ADR-002).
