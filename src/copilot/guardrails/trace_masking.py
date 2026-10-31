"""Day 7 step 7: LangSmith trace masking (sprint doc: "anonymizer rules, hidden restricted
payloads").

Purpose : stop PII, secrets, and restricted-table/view names from ever being *stored* in a
          LangSmith trace, independent of the Guardian (which only ever sees the Orchestrator's
          final answer) -- a trace captures every intermediate LLM call's raw inputs/outputs,
          including specialist prompts that reference Restricted tables by name on their way to
          a correctly-redacted final answer. Those intermediate payloads need their own masking;
          waiting for the Guardian's one pass at the end would be too late for anything already
          shipped to LangSmith's servers.
Inputs  : the `inputs`/`outputs` dict `langsmith.run_helpers.traceable` builds for one LLM call.
Outputs : the same shape, with every string value masked in place.

**Why `process_inputs`/`process_outputs`, not a `Client(anonymizer=...)`:** `@traceable`'s own
decorator-level `process_inputs`/`process_outputs` kwargs run locally, synchronously, as a plain
closure call -- no `Client` object, no network call, and (confirmed with a throwaway script
before wiring this in) no construction-time `GET /info` call to LangSmith's API the way building
a `langsmith.Client()` does eagerly. A `Client(anonymizer=...)` would also have to be threaded
through every one of this project's dozen `LLMClient.complete`/`.structured()` call sites (or
be set as langsmith's own default client), and `contextvars`-based "set it once, globally"
options don't survive crossing into `_run_specialist`'s `ThreadPoolExecutor` worker thread
(confirmed empirically -- a `ContextVar.set()` in the main thread is invisible to a plain
`threading.Thread`/`ThreadPoolExecutor` target). Decorating `LLMClient.complete`/`.structured`
themselves with `process_inputs=mask_run_payload, process_outputs=mask_run_payload` sidesteps
both problems: it's baked into the ONE choke point every call already goes through, as a plain
function reference -- no Client, no contextvars, no per-call-site changes needed anywhere else
in the codebase.

**Why `copilot.guardrails.secret_patterns`, not `guardian.SECRET_PATTERNS`, directly:**
`guardian.py` imports `copilot.agents.contracts` (for `AgentResult`'s type hint), which itself
imports `copilot.llm.client` (for `Effort`) -- so `trace_masking.py` importing from `guardian.py`
while `llm/client.py` imports `trace_masking.py` is a real cycle (confirmed by actually hitting
`ImportError: cannot import name 'Effort' from partially initialized module` before this was
split out). `secret_patterns.py` is a leaf module with nothing above it in the dependency graph,
so both `guardian.py` and this module import the same patterns from there instead.

**Why "hidden restricted payloads" short-circuits everything else:** if a Restricted table/view
name (`policies/disclosure.yaml`'s `restricted_names` -- the same list `Guardian._check_
restricted_names` blocks on) appears anywhere in a payload, the whole payload is replaced with
one marker rather than selectively redacting just that name. A payload that names a Restricted
source is already in territory this project's licence/disclosure rules say shouldn't be
retained anywhere outside the app's own request path -- partial redaction would still leave
everything else in that payload (the rest of a prompt, other context) sitting in LangSmith.
"""

from __future__ import annotations

from typing import Any

from copilot.guardrails.pii import find_pii
from copilot.guardrails.policy import DisclosurePolicy, load_policy
from copilot.guardrails.secret_patterns import SECRET_PATTERNS

RESTRICTED_PAYLOAD_MARKER = "[RESTRICTED PAYLOAD HIDDEN -- see data/audit/guardian_log.jsonl]"

_policy_cache: DisclosurePolicy | None = None


def _policy() -> DisclosurePolicy:
    """Cached the same way `copilot.guardrails.canary._policy()` is -- loaded once, not once per
    masked call (`process_inputs`/`process_outputs` fire on every single LLM call).
    """
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = load_policy()
    return _policy_cache


def _mask_string(text: str) -> str:
    masked = text
    for entity in find_pii(masked):
        masked = masked.replace(entity.text, f"[REDACTED:{entity.entity_type}]")
    for name, pattern in SECRET_PATTERNS.items():
        masked = pattern.sub(f"[REDACTED:{name}]", masked)
    return masked


def _as_plain(value: Any) -> Any:  # noqa: ANN401
    """Pydantic models (structured outputs, CallMetrics) become dicts so they get masked too."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:  # noqa: BLE001 -- fall back to the object itself
            return value
    return value


def _mask_value(value: Any) -> Any:  # noqa: ANN401 -- recurses over arbitrary JSON-ish data
    value = _as_plain(value)
    if isinstance(value, str):
        return _mask_string(value)
    if isinstance(value, dict):
        return {k: _mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_value(v) for v in value]
    return value


def _contains_restricted_name(value: Any, names: frozenset[str]) -> bool:  # noqa: ANN401
    if not names:
        return False
    value = _as_plain(value)
    if isinstance(value, str):
        return any(name in value for name in names)
    if isinstance(value, dict):
        return any(_contains_restricted_name(v, names) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_restricted_name(v, names) for v in value)
    return False


def mask_run_payload(payload: Any) -> dict[str, Any]:  # noqa: ANN401
    """The function passed as both `process_inputs` and `process_outputs` on
    `LLMClient.complete`/`.structured`'s `@traceable` decorators. Same shape in, same shape out
    (a dict) -- `@traceable` requires that; it's what gets *recorded*, not what the decorated
    function actually returns to its caller, so masking here never changes real behaviour.
    """
    # 31 Oct 2026: LangSmith passes a function's raw return value to process_outputs when it
    # isn't a dict. LLMClient.structured returns a (model, CallMetrics) tuple, so every call
    # logged "process_outputs failed ... 'tuple' object has no attribute 'items'" and its
    # outputs were dropped from the trace. Wrap anything that isn't a dict.
    if not isinstance(payload, dict):
        payload = {"output": payload}
    names = frozenset(_policy().restricted_names)
    if _contains_restricted_name(payload, names):
        return {"_masked": RESTRICTED_PAYLOAD_MARKER}
    return {key: _mask_value(value) for key, value in payload.items()}


__all__ = ["RESTRICTED_PAYLOAD_MARKER", "mask_run_payload"]
