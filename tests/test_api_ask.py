"""Tests for POST /ask (SSE, behind auth + rate limiting) and POST /auth/redeem.

Every dependency that would otherwise need a real API key, a real snapshot, or a real Chroma
index (`get_orchestrator`) or touch a shared file (`get_auth_store`, the rate limiters, the
budget tracker) is overridden via `app.dependency_overrides` -- the standard FastAPI testing
idiom, and the only way these endpoints are testable at all without the real infrastructure
`scripts/run_orchestrator_golden.py` already documents needing. No network, no real API key,
same convention as `tests/test_llm_client.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilot.agents.contracts import AgentResult, TaskSpec
from copilot.agents.orchestrator import Orchestrator
from copilot.api.auth import AuthStore
from copilot.api.dependencies import (
    get_auth_store,
    get_ip_rate_limiter,
    get_orchestrator,
    get_user_budget_tracker,
    get_user_rate_limiter,
)
from copilot.api.main import app
from copilot.api.rate_limit import DailyBudgetTracker, RequestRateLimiter
from copilot.llm.client import LLMClient
from copilot.settings import get_settings
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _fake_orchestrator() -> Orchestrator:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(  # type: ignore[attr-defined]
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            structured_response(
                {
                    "grounded": True,
                    "citations_ok": True,
                    "sufficient": True,
                    "contradictions": [],
                    "feedback": "",
                }
            ),
        ]
    )

    def _run(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id,
            agent="data_analyst",
            status="ok",
            findings="x",
            data_classes=["internal"],
            cost_usd=0.001,
            latency_s=0.1,
            llm_calls=1,
        )

    return Orchestrator(llm, executors={"data_analyst": _run})


def _fake_action_orchestrator(checkpoint_path: str) -> Orchestrator:
    """Same shape as `tests/test_orchestrator.py`'s own `_action_plan_llm()` fixture: a plan
    naming the `action` agent, which the Guardian allows -- the one path that reaches the
    approval gate -- so `/ask/approve` has a real paused thread to resume.
    """
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(  # type: ignore[attr-defined]
        [
            structured_response(
                {
                    "tasks": [
                        {"agent": "action", "objective": "draft a reorder email", "constraints": {}}
                    ]
                }
            ),
            structured_response(
                {
                    "answer": "Draft: confirm the reorder, thanks.",
                    "cited_tasks": ["t0"],
                    "conflicts_noted": [],
                }
            ),
            structured_response(
                {
                    "grounded": True,
                    "citations_ok": True,
                    "sufficient": True,
                    "contradictions": [],
                    "feedback": "",
                }
            ),
        ]
    )

    def _run(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id,
            agent="action",
            status="ok",
            findings="x",
            data_classes=["public"],
            cost_usd=0.001,
            latency_s=0.1,
            llm_calls=1,
        )

    return Orchestrator(llm, executors={"action": _run}, checkpoint_path=checkpoint_path)


@pytest.fixture
def auth_store(tmp_path) -> AuthStore:  # noqa: ANN001
    return AuthStore(tmp_path / "auth_store.json")


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, auth_store: AuthStore, tmp_path
) -> Iterator[TestClient]:  # noqa: ANN001
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    app.dependency_overrides[get_auth_store] = lambda: auth_store
    app.dependency_overrides[get_orchestrator] = _fake_orchestrator
    app.dependency_overrides[get_user_rate_limiter] = lambda: RequestRateLimiter(1000)
    app.dependency_overrides[get_ip_rate_limiter] = lambda: RequestRateLimiter(1000)
    app.dependency_overrides[get_user_budget_tracker] = lambda: DailyBudgetTracker(
        tmp_path / "daily_user_spend.json"
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        data_line = next(line for line in lines if line.startswith("data: "))
        import json

        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


def test_redeem_invite_then_ask_streams_an_answer(
    client: TestClient, auth_store: AuthStore
) -> None:
    invite = auth_store.issue_invite(role="analyst", label="smoke test")

    redeemed = client.post("/auth/redeem", json={"invite_code": invite, "label": "smoke test"})
    assert redeemed.status_code == 200
    api_key = redeemed.json()["api_key"]
    assert redeemed.json()["role"] == "analyst"

    response = client.post(
        "/ask",
        json={"question": "What is total freight cost?"},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["answer"] == "ok"
    node_events = [e for e in events if e["type"] == "node"]
    assert [e["node"] for e in node_events] == [
        "plan",
        "run_specialist",
        "draft",
        "verify",
        "finalize",
        "guardian",
    ]


def test_redeeming_an_unknown_invite_code_is_rejected(client: TestClient) -> None:
    response = client.post("/auth/redeem", json={"invite_code": "not-a-real-code", "label": "x"})
    assert response.status_code == 400


def test_ask_without_a_bearer_token_is_rejected(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "anything"})
    assert response.status_code == 401


def test_ask_with_an_unknown_api_key_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/ask",
        json={"question": "anything"},
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert response.status_code == 401


def test_ask_is_rejected_once_the_per_user_rate_limit_is_exhausted(
    client: TestClient, auth_store: AuthStore
) -> None:
    api_key = auth_store.issue_api_key(role="analyst", label="x")
    tight_limiter = RequestRateLimiter(1)  # one shared instance -- a fresh one each call would
    # never see its own previous hit, so the second request would always look like the first.
    app.dependency_overrides[get_user_rate_limiter] = lambda: tight_limiter

    first = client.post(
        "/ask",
        json={"question": "one"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    second = client.post(
        "/ask",
        json={"question": "two"},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_ask_is_rejected_once_the_per_user_daily_budget_is_exhausted(
    client: TestClient, auth_store: AuthStore, tmp_path
) -> None:  # noqa: ANN001
    api_key = auth_store.issue_api_key(role="analyst", label="x")
    principal = auth_store.authenticate(api_key)
    budget = DailyBudgetTracker(tmp_path / "daily_user_spend.json")
    budget.record(principal.key_id, 999.0)  # already far over any sane cap
    app.dependency_overrides[get_user_budget_tracker] = lambda: budget

    response = client.post(
        "/ask",
        json={"question": "anything"},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 429


def test_approve_resumes_a_paused_action_draft_for_an_approver(
    client: TestClient, auth_store: AuthStore, tmp_path: Path
) -> None:
    db_path = str(tmp_path / "ui_approval_checkpoints.sqlite")
    app.dependency_overrides[get_orchestrator] = lambda: _fake_action_orchestrator(db_path)
    analyst_key = auth_store.issue_api_key(role="analyst", label="asker")
    approver_key = auth_store.issue_api_key(role="approver", label="reviewer")

    asked = client.post(
        "/ask",
        json={"question": "draft a reorder email", "thread_id": "ui-thread-1"},
        headers={"Authorization": f"Bearer {analyst_key}"},
    )
    assert asked.status_code == 200
    events = _parse_sse(asked.text)
    assert events[-1]["result"]["pending_approval"] is True

    approved = client.post(
        "/ask/approve",
        json={"thread_id": "ui-thread-1", "decision": "approve"},
        headers={"Authorization": f"Bearer {approver_key}"},
    )

    assert approved.status_code == 200
    body = approved.json()
    assert body["pending_approval"] is False
    assert body["approval_decision"] == "approved"
    assert body["answer"] == "Draft: confirm the reorder, thanks."


def test_approve_is_rejected_for_a_non_approver_role(
    client: TestClient, auth_store: AuthStore, tmp_path: Path
) -> None:
    db_path = str(tmp_path / "ui_approval_checkpoints_2.sqlite")
    app.dependency_overrides[get_orchestrator] = lambda: _fake_action_orchestrator(db_path)
    analyst_key = auth_store.issue_api_key(role="analyst", label="asker")

    asked = client.post(
        "/ask",
        json={"question": "draft a reorder email", "thread_id": "ui-thread-2"},
        headers={"Authorization": f"Bearer {analyst_key}"},
    )
    assert asked.status_code == 200

    response = client.post(
        "/ask/approve",
        json={"thread_id": "ui-thread-2", "decision": "approve"},
        headers={"Authorization": f"Bearer {analyst_key}"},  # analyst, not approver/admin
    )

    assert response.status_code == 403


def test_ui_root_serves_the_static_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Vendor Intelligence Copilot" in response.text


def test_static_assets_are_served_under_static(client: TestClient) -> None:
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "askQuestion" in response.text
