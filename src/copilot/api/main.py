"""FastAPI application: the HTTP entry point of the Copilot.

Purpose : Day 2 walking skeleton (/health, /version) plus Day 8's real endpoints: /ask (the
          Orchestrator, streamed over SSE, behind auth + rate limiting) and /auth/redeem (a
          human's self-service invite-code -> API-key exchange).
Inputs  : settings from the environment (.env locally); in prod, secrets from SSM at start-up.
Outputs : JSON responses for /health, /version, /auth/redeem; a `text/event-stream` SSE body
          for /ask (one `copilot.agents.orchestrator.StreamEvent` per server-sent event).
Run     : uv run uvicorn copilot.api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from copilot.agents.orchestrator import Orchestrator
from copilot.api.auth import AuthStore, InvalidCredential, Principal
from copilot.api.dependencies import (
    enforce_rate_limits,
    get_auth_store,
    get_orchestrator,
    get_user_budget_tracker,
    require_any_role,
)
from copilot.api.rate_limit import DailyBudgetTracker
from copilot.guardrails.policy import Role
from copilot.secrets import load_into_environ
from copilot.settings import get_settings

log = logging.getLogger("copilot.api")


class Health(BaseModel):
    status: str


class VersionInfo(BaseModel):
    version: str
    git_sha: str
    env: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Runs once at start-up. In prod, pull secrets from SSM before anything uses them."""
    settings = get_settings()
    if settings.app_env == "prod":
        names = load_into_environ(settings.ssm_prefix, settings.aws_region)
        get_settings.cache_clear()  # re-read settings now that the secrets are in the env
        log.info("loaded %d parameters from SSM: %s", len(names), names)  # names only
    yield


app = FastAPI(title="Vendor Intelligence Copilot API", lifespan=lifespan)


@app.get("/health", response_model=Health)
def health() -> Health:
    """Liveness: cheap, no dependencies, used by Docker, the deploy script and uptime checks."""
    return Health(status="ok")


@app.get("/version", response_model=VersionInfo)
def version() -> VersionInfo:
    """Which code is running: package version, Git commit and environment."""
    s = get_settings()
    return VersionInfo(
        version=package_version("vendor-intelligence-copilot"), git_sha=s.git_sha, env=s.app_env
    )


class RedeemInviteRequest(BaseModel):
    invite_code: str
    label: str = Field(min_length=1, max_length=200)


class RedeemInviteResponse(BaseModel):
    api_key: str
    role: Role


@app.post("/auth/redeem", response_model=RedeemInviteResponse)
def redeem_invite(
    body: RedeemInviteRequest, auth_store: AuthStore = Depends(get_auth_store)
) -> RedeemInviteResponse:
    """Day 8 step 4: the one HTTP-reachable way a human turns an out-of-band invite code (from
    `scripts/issue_invite_code.py`, run by an admin) into a long-lived API key. Returns the raw
    key exactly once -- `copilot.api.auth.AuthStore`'s own docstring explains why there is no
    way to retrieve it again after this response.
    """
    try:
        key = auth_store.redeem_invite(body.invite_code, label=body.label)
    except InvalidCredential as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    role = auth_store.authenticate(key).role
    return RedeemInviteResponse(api_key=key, role=role)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = None


def _sse_lines(
    orchestrator: Orchestrator,
    question: str,
    role: Role,
    thread_id: str | None,
    *,
    key_id: str,
    budget: DailyBudgetTracker,
) -> Iterator[str]:
    """One `data: <json>\\n\\n` line per `StreamEvent` -- the plain SSE wire format (see
    https://html.spec.whatwg.org/multipage/server-sent-events.html), no extra library needed
    for a stream this simple. `event: <type>` precedes each `data:` line so a client (or
    `EventSource`-style parser) can dispatch on `event.type` without parsing the JSON body
    first; `copilot.agents.orchestrator.StreamEvent`'s own docstring lists what `node`/`result`
    events each carry.

    Also where this caller's per-identity daily budget (A2 §1.6) actually accrues: the run's
    real `total_cost_usd` isn't known until the trailing `type="result"` event, so it's recorded
    here, the moment that event is in hand, against `key_id` -- `enforce_rate_limits` only ever
    checks *past* spend against the cap (same "the gate can't know this request's own cost
    before it exists" limitation `InputGate`'s own per-role spend check has), so this is the
    other half: making sure there is a "past" for the *next* request to see.
    """
    for event in orchestrator.stream_answer(question, role=role, thread_id=thread_id):
        if event.type == "result" and event.result is not None:
            budget.record(key_id, event.result.total_cost_usd)
        yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@app.post("/ask")
def ask(
    body: AskRequest,
    principal: Principal = Depends(require_any_role),
    _rate_limit: None = Depends(enforce_rate_limits),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    budget: DailyBudgetTracker = Depends(get_user_budget_tracker),
) -> StreamingResponse:
    """Day 8 step 3: the Orchestrator, behind auth + rate limiting, streamed over SSE.

    Auth resolves `principal.role`, which is what the question actually runs as -- a caller
    never supplies its own role; the API key it authenticated with is the only source of truth
    for that, same as every other guardrail in this project (the input gate, the Guardian) only
    ever trusts a `Role` the caller couldn't have forged. The answer itself is released to the
    caller only after it has passed through the Guardian (`finalize -> guardian` is the one path
    to `END`, unchanged by this endpoint); an ESCALATE shows up as `pending_review` on the final
    `StreamEvent(type="result", ...)`'s `OrchestratorResult`, not a separate hidden step --
    `copilot.agents.orchestrator.PendingReview`'s own docstring covers what a caller does with
    that `review_id`.
    """
    return StreamingResponse(
        _sse_lines(
            orchestrator,
            body.question,
            principal.role,
            body.thread_id,
            key_id=principal.key_id,
            budget=budget,
        ),
        media_type="text/event-stream",
    )
