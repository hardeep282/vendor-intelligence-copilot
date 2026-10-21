"""FastAPI dependency wiring for the API's auth, rate-limit and orchestrator needs.

Purpose : one place that constructs the (mostly expensive, real-key-requiring) singletons
          `/ask` and `/auth/redeem` need, and the small `Depends()` callables that read a
          request's `Authorization` header / client IP against them. Kept out of `main.py` so
          that module stays the thin routing layer it already was (Day 2) -- this is the part
          that changes if auth storage or rate-limit policy ever does.
Inputs  : nothing at import time; everything here is a dependency, resolved per-request.
Outputs : FastAPI dependency callables (`require_role`, `enforce_rate_limits`) and the cached
          singleton getters tests override via `app.dependency_overrides`.

**`get_orchestrator()` is built lazily, on first use, not at app start-up** -- unlike
`get_auth_store()`/the rate limiters (cheap, no external dependency), a real `Orchestrator`
needs a real `ANTHROPIC_API_KEY`, the real DuckDB snapshot, and the real Chroma index built
(same requirements `scripts/run_orchestrator_golden.py` already documents). Building it at
start-up would make `/health`/`/version` -- meant to be cheap liveness checks with no
dependencies, per that module's own docstring -- fail to start the whole process in any
environment missing those (every test environment included). `@lru_cache` means it still only
builds once per process, the first time `/ask` is actually called; tests never call it at all,
overriding the dependency with a fake `Orchestrator` instead (`tests/test_api_ask.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from fastapi import Depends, Header, HTTPException, Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from copilot.agents.contracts import AgentBudget
from copilot.agents.orchestrator import Orchestrator
from copilot.agents.wiring import build_executors
from copilot.api.auth import AuthStore, InvalidCredential, Principal
from copilot.api.rate_limit import DailyBudgetTracker, RequestRateLimiter
from copilot.data import store
from copilot.guardrails.policy import Role, load_policy
from copilot.llm.client import LLMClient
from copilot.rag.chunking import chunk_corpus
from copilot.rag.corpus import load_corpus
from copilot.rag.corrective import CorrectiveRagService
from copilot.rag.embeddings import SentenceTransformerEmbedder
from copilot.rag.permissions import PermissionedRetriever
from copilot.rag.store import ChunkStore, get_chroma_client
from copilot.settings import REPO_ROOT, get_settings
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import load_rules

CHECKPOINT_PATH = str(REPO_ROOT / "data" / "orchestrator_checkpoints.sqlite")


def _build_checkpointer() -> BaseCheckpointSaver[str]:
    """Day 8 step 7: Postgres in prod (or wherever `CHECKPOINT_DATABASE_URL` is set), local
    SQLite everywhere else -- the orchestrator module stays storage-agnostic (see
    `Orchestrator.__init__`'s docstring), this is the one place that decides which store a real
    server run gets. A `ConnectionPool`, not a single `Connection`, because this object is
    shared across every concurrent request in the process for its whole lifetime (same
    process-lifetime-singleton posture as `get_auth_store`/the rate limiters) -- a single
    psycopg `Connection` is not safe for that; `PostgresSaver` accepts either and a pool is the
    one actually meant for concurrent callers. `.setup()` runs LangGraph's own idempotent
    `CREATE TABLE IF NOT EXISTS` migration -- safe to call on every start-up, including against
    a database another replica already migrated.
    """
    settings = get_settings()
    dsn = settings.checkpoint_database_url
    if dsn is not None and dsn.get_secret_value():
        pool = cast(
            "ConnectionPool[Connection[dict[str, Any]]]",
            ConnectionPool(
                conninfo=dsn.get_secret_value(),
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=True,
            ),
        )
        pg_checkpointer = PostgresSaver(pool)
        pg_checkpointer.setup()
        return pg_checkpointer
    return SqliteSaver(sqlite3.connect(CHECKPOINT_PATH, check_same_thread=False))


@lru_cache
def get_auth_store() -> AuthStore:
    return AuthStore()


@lru_cache
def get_user_rate_limiter() -> RequestRateLimiter:
    return RequestRateLimiter(get_settings().per_user_rate_limit_per_minute)


@lru_cache
def get_ip_rate_limiter() -> RequestRateLimiter:
    return RequestRateLimiter(get_settings().per_ip_rate_limit_per_minute)


@lru_cache
def get_user_budget_tracker() -> DailyBudgetTracker:
    return DailyBudgetTracker()


@lru_cache
def get_orchestrator() -> Orchestrator:
    """Exactly `scripts/run_orchestrator_golden.py`'s own real-service wiring, reused rather
    than re-derived -- this module's docstring explains why it's built lazily, cached, here.
    """
    llm = LLMClient()
    policy = load_policy()
    con = store.connect()
    sql_service = TextToSqlService(llm, con=con, policy=policy, rules=load_rules())
    chunks = chunk_corpus(load_corpus())
    chunk_store = ChunkStore(get_chroma_client())
    retriever = PermissionedRetriever(chunks, chunk_store, SentenceTransformerEmbedder(), policy)
    rag_service = CorrectiveRagService(llm, retriever)
    executors = build_executors(
        llm=llm,
        sql_service=sql_service,
        rag_service=rag_service,
        retriever=retriever,
        con=con,
        policy=policy,
    )
    return Orchestrator(
        llm,
        executors=executors,
        default_budget=AgentBudget(max_latency_s=60.0),
        checkpointer=_build_checkpointer(),
    )


def require_role(*allowed: Role) -> Callable[..., Principal]:
    """Returns a `Depends()`-compatible callable that authenticates the `Authorization: Bearer
    <api-key>` header against `AuthStore` and checks `principal.role in allowed`. A factory, not
    a single shared dependency, so each route states its own allowed roles (`/ask` needs any
    authenticated role; a future admin-only route would pass `require_role("admin")`) --
    mirrors `Orchestrator.resume_approval`'s own `approver_role in (...)` check, just lifted to
    the HTTP boundary instead of a Python method call.
    """

    def _dependency(
        authorization: str | None = Header(default=None),
        auth_store: AuthStore = Depends(get_auth_store),
    ) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
        raw_key = authorization.removeprefix("Bearer ").strip()
        try:
            principal = auth_store.authenticate(raw_key)
        except InvalidCredential as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if principal.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"role '{principal.role}' may not call this endpoint",
            )
        return principal

    return _dependency


#: Every `/ask`-style route needs *some* authenticated caller, any role -- role-specific
#: restrictions (an admin-only route, say) would call `require_role("admin")` instead. Defined
#: once at module level, not inline per route, so `enforce_rate_limits` below and a route's own
#: `principal` parameter resolve to the exact same `Depends()` call -- FastAPI caches a
#: dependency's result per request by the identity of the callable, so sharing this one object
#: (rather than two separate `require_role(...)` calls that look identical but aren't `is`-equal)
#: is what keeps authentication running exactly once per request, not twice.
require_any_role = require_role("viewer", "analyst", "approver", "admin")


def enforce_rate_limits(
    request: Request,
    principal: Principal = Depends(require_any_role),
    user_limiter: RequestRateLimiter = Depends(get_user_rate_limiter),
    ip_limiter: RequestRateLimiter = Depends(get_ip_rate_limiter),
    budget: DailyBudgetTracker = Depends(get_user_budget_tracker),
) -> None:
    """Day 8, A2 §1.6: the per-identity/per-IP/per-identity-daily-budget guard, run *after*
    `require_role` resolves a `Principal` (there's no identity to rate-limit before that) and
    *before* the Orchestrator -- or even the input gate -- ever sees the request, same
    cheapest-checks-first posture `InputGate.review` and `Guardian.review` both already take.
    Raises `HTTPException(429)` on the first check that fails; does not check the rest (no
    point refining which of three limits a request also would have hit).
    """
    if not user_limiter.allow(principal.key_id):
        raise HTTPException(status_code=429, detail="rate limit exceeded for this API key")
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded for this client IP")
    settings = get_settings()
    if budget.spent_today(principal.key_id) >= settings.per_user_daily_budget_usd:
        raise HTTPException(
            status_code=429,
            detail=(
                f"daily budget of ${settings.per_user_daily_budget_usd:.2f} exhausted for this "
                "API key; resets at UTC midnight"
            ),
        )


__all__ = [
    "enforce_rate_limits",
    "get_auth_store",
    "get_ip_rate_limiter",
    "get_orchestrator",
    "get_user_budget_tracker",
    "get_user_rate_limiter",
    "require_any_role",
    "require_role",
]
