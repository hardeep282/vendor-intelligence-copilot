"""The one place the secret-shape regexes live -- a leaf module (no project imports) so both
`copilot.guardrails.guardian` (BLOCKs a secret out of a user-facing answer) and `copilot.
guardrails.trace_masking` (Day 7 step 7: masks a secret out of a LangSmith trace) can share the
exact same patterns without one importing the other. `guardian.py` previously defined these
itself; `trace_masking.py` importing `guardian.SECRET_PATTERNS` would have created a real import
cycle (`llm.client -> trace_masking -> guardian -> agents.contracts -> llm.client`, confirmed by
actually trying it before this module existed) -- splitting the regexes out here, with nothing
above them in the dependency graph, breaks that cycle while keeping one source of truth for
"what a secret shape looks like".
"""

from __future__ import annotations

import re

# Cheap regexes for the handful of credential shapes this project's own .env.example documents
# (Anthropic, AWS, LangSmith/generic bearer tokens) -- not a general secret scanner (that's
# gitleaks's job, already in pre-commit/CI per ADR-004); these run on LLM *output* and on trace
# payloads, neither of which gitleaks ever sees.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_api_key": re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S{20,}"),
    "generic_bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9\-_.]{20,}\b"),
}

__all__ = ["SECRET_PATTERNS"]
