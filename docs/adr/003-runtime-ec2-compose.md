# ADR-003: One EC2 host running Docker Compose behind host nginx

Date: 2026-10-13 · Status: Accepted (scale-up path documented, not built)

## Context
The sprint needs a public HTTPS API by Day 2 at the lowest cost, with a path to agents,
Chroma and Postgres later.

## Options
1. EC2 + Docker Compose + nginx/Certbot on the host.
2. ECS Fargate + ALB + ACM.
3. App Runner.

## Decision
Option 1 on **t3.small (x86, 2 vCPU, 2 GiB), Ubuntu 24.04, gp3 20 GB, Mumbai**, with:
- SSM Session Manager instead of SSH (no port 22 open), Elastic IP, security group 80/443 only.
- IMDSv2 required with **hop limit 2**, so containers can use the instance role.
- CPU credits set to **standard** so a busy CPU cannot add surprise charges.
- x86 rather than Graviton: GitHub's arm64 runners and private-repo terms add uncertainty;
  revisit when costs matter more than build simplicity.

Option 2 adds an ALB (a fixed monthly cost) before there is any traffic; option 3 cannot run
the Chroma and Postgres sidecars planned for Days 4 and 8.

## Consequences
- Single host: no high availability. Acceptable for a portfolio demo; the README says so.
- Upgrade path: t3.medium when agents + Chroma + Postgres need 4 GiB; later ALB + ASG or ECS.
- Estimated cost about $22 per month in Mumbai (see BUILD_LOG Day 2).
