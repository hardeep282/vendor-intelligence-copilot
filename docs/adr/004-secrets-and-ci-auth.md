# ADR-004: Secrets in SSM, per-environment keys, OIDC for CI

Date: 2026-10-13 · Status: Accepted

## Decision
- **Separate keys per environment.** Dev keys (Anthropic, LangSmith) live only in the local
  `.env` (git-ignored). Prod keys are different keys, stored only in SSM Parameter Store as
  SecureString under `/vendor-copilot/prod/`.
- **The app reads prod secrets at start-up** with the EC2 instance role
  (`copilot.secrets.load_into_environ`). Nothing secret is baked into images, compose files,
  GitHub variables or user data. Only parameter names are logged, never values.
- **Least privilege.** The instance role can read only `/vendor-copilot/prod/*`; decryption is
  allowed only through SSM (`kms:ViaService`).
- **CI uses GitHub OIDC, not stored AWS keys.** The deploy role trusts only tokens for
  `repo:hardeep282/vendor-intelligence-copilot:ref:refs/heads/main` and can push to one ECR
  repository and run commands on one instance.
- **Leak prevention:** gitleaks in pre-commit and in CI (full history). Spend limits on the
  provider console; the app's own daily spend cap arrives on Day 7.

## Why not GitHub Environments for the trust condition?
Environments in private repositories depend on the GitHub plan. A branch-scoped trust policy
gives the same protection for a single-maintainer repo without that dependency.

## Consequences
Rotating a key = put a new SSM value and restart the container. The leaked-key runbook is
written on Day 8.
