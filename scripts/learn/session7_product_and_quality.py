"""Learning script for session 7: the product and quality layer (API, logins, CI, eval gate).

Purpose : run the real FastAPI app in-process (no server, no port, no network) in eight small,
          numbered steps, so you can watch a request go through logins, rate limits and the
          live stream in VS Code's debugger. **No real Claude call is made**: the orchestrator
          behind `/ask` gets scripted replies from the tests' stand-in
          (`tests/fakes/anthropic_fakes.py`), and its one specialist is the real plain-code
          forecast, on your real snapshot. Then it reads the CI pipeline and the eval gate's
          pass marks straight from their files.
Inputs  : the local snapshot (build it first with `uv run python scripts/build_snapshot.py`),
          .github/workflows/ci.yml and evals/thresholds.yaml (both in the repo).
Outputs : plain-English printout of each step. Logins, spend and the audit log go to a
          temporary folder, never to your real data/ files.

How to use it in VS Code (see the Code Trail page, chapter 4): put a red dot on the first line
inside any `step_...` function, press F5, pick "Python Debugger: Current File", then F10 / F11.
Or just run it:
    uv run python scripts/learn/session7_product_and_quality.py

Added 10 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from copilot.agents.orchestrator import Orchestrator
from copilot.agents.specialists import run_forecasting_risk
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
from copilot.cli import use_utf8_output
from copilot.guardrails import audit_log
from copilot.guardrails.input_gate import InputGate, SpendTracker
from copilot.llm.client import LLMClient
from copilot.settings import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))  # so the tests' Claude stand-in can be imported
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response  # noqa: E402

QUESTION = "What's next quarter's portfolio demand?"


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def scripted_orchestrator(tmp: Path) -> Orchestrator:
    """The real orchestrator with scripted Claude and the real forecast specialist."""
    llm = LLMClient(api_key="sk-test-not-real")  # a made-up key; nothing is ever sent
    llm._client.messages = FakeMessagesResource(  # type: ignore[misc,assignment]
        [
            structured_response(
                {"tasks": [{"agent": "forecasting_risk", "objective": "next quarter"}]}
            ),
            structured_response({"answer": "About 3.76M units a month.", "cited_tasks": ["t0"]}),
            structured_response({"grounded": True, "citations_ok": True, "sufficient": True}),
        ]
    )
    gate = InputGate(spend_tracker=SpendTracker(tmp / "spend.json"), kill_switch_enabled=False)
    return Orchestrator(llm, executors={"forecasting_risk": run_forecasting_risk}, input_gate=gate)


def step_1_the_routes(client: TestClient) -> None:
    """Every address the app answers, read from the app itself."""
    heading(1, "The routes: what the API offers")
    for path, methods in sorted(client.get("/openapi.json").json()["paths"].items()):
        print(f"  {', '.join(m.upper() for m in methods):<6} {path}")
    print("\n  Plus /docs, the interactive page FastAPI builds from these.")


def step_2_cheap_health_checks(client: TestClient) -> None:
    """Health and version need nothing: no key, no data, no Claude."""
    heading(2, "Health and version: the checks the server and CI rely on")
    print(f"  GET /health  -> {client.get('/health').status_code} {client.get('/health').json()}")
    print(f"  GET /version -> {client.get('/version').json()}")


def step_3_no_login_no_answer(client: TestClient) -> None:
    """/ask refuses a request with no key, before anything else runs."""
    heading(3, "Ask without logging in")
    r = client.post("/ask", json={"question": QUESTION})
    print(f"  POST /ask with no key -> {r.status_code} {r.json()['detail']}")


def step_4_invite_to_key(client: TestClient, store: AuthStore) -> str:
    """An admin issues an invite; the person swaps it for a key, once."""
    heading(4, "Invite code -> API key")
    invite = store.issue_invite("analyst", label="learning session")
    r = client.post("/auth/redeem", json={"invite_code": invite, "label": "my laptop"})
    body = r.json()
    print(f"  invite code issued (shown once): {invite[:10]}...")
    key_start = str(body["api_key"])[:10]
    print(f"  POST /auth/redeem -> {r.status_code}, role {body['role']}, key {key_start}...")
    again = client.post("/auth/redeem", json={"invite_code": invite, "label": "again"})
    print(f"  the same invite a second time -> {again.status_code} {again.json()['detail']}")
    print("  Only a hash of each key is stored, so a stolen file can't be used to log in.")
    return str(body["api_key"])


def step_5_the_live_stream(client: TestClient, key: str) -> None:
    """The answer arrives as a stream of events: progress first, the result last."""
    heading(5, "Ask with a key: the answer streams back (server-sent events)")
    headers = {"Authorization": f"Bearer {key}"}
    with client.stream("POST", "/ask", json={"question": QUESTION}, headers=headers) as r:
        print(f"  status {r.status_code}, content-type {r.headers['content-type']}")
        for line in r.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line.removeprefix("data: "))
                if event["type"] == "node":
                    print(f"    event: node    {event['node']}")
                else:
                    res = event["result"]
                    print(
                        f"    event: result  verified={res['verified']}  "
                        f"guardian={res['guardian_verdict']['outcome']}"
                    )
                    print(f"                   answer: {res['answer']}")


def step_6_rate_limits(client: TestClient, key: str) -> None:
    """Per-key and per-address limits answer 429 before the orchestrator is even reached."""
    heading(6, "Rate limits: the third request in a minute is refused")
    app.dependency_overrides[get_user_rate_limiter] = lambda: limiter
    headers = {"Authorization": f"Bearer {key}"}
    for i in range(1, 4):
        r = client.post("/ask", json={"question": ""}, headers=headers)  # empty: fails fast
        print(f"  request {i}: {r.status_code}")
    print("  1-2: 422, the empty question fails the request model, but each still counts;")
    print("  3: 429, over the limit of 2 a minute, so it's refused before anything else.")


limiter = RequestRateLimiter(max_per_minute=2)


def step_7_the_ci_pipeline() -> None:
    """What runs on every push, read from .github/workflows/ci.yml."""
    heading(7, "The CI pipeline: five jobs")
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    when = {
        "eval-gate": "pull requests into main only",
        "deploy": "pushes to main, once AWS is set up; it isn't yet",
    }
    setup = ("actions/checkout", "astral-sh/setup-uv", "Install locked dependencies")
    for name, job in ci["jobs"].items():
        steps = [s.get("name") or s.get("uses", "").split("@")[0] for s in job.get("steps", [])]
        print(f"  {name:<12} ({when.get(name, 'every push')})")
        print(f"      {' -> '.join(x for x in steps if x not in setup)}")


def step_8_the_eval_gate() -> None:
    """The pass marks a release must clear, read from evals/thresholds.yaml."""
    heading(8, "The eval gate's pass marks")
    t = yaml.safe_load((REPO_ROOT / "evals" / "thresholds.yaml").read_text("utf-8"))
    must_pass = t["deterministic"]["pytest_must_all_pass"]
    print(f"  deterministic layer: every test must pass = {must_pass}")
    judged = t["llm_judged"]
    print(f"  AI-judged layer, spend ceiling ${judged['max_llm_budget_usd']:.2f} per run:")
    for suite, marks in judged.items():
        if isinstance(marks, dict):
            for metric, value in marks.items():
                print(f"    {suite:<16} {metric:<26} {value}")
    print("\n  Without a key (as in CI today) the AI-judged layer reports SKIP, never a")
    print("  made-up PASS.")


def main() -> None:
    use_utf8_output()
    tmp = Path(tempfile.mkdtemp(prefix="copilot-learn-"))
    audit_log.DEFAULT_AUDIT_LOG_PATH = tmp / "guardian_log.jsonl"  # keep your real log clean
    store = AuthStore(tmp / "auth_store.json")
    app.dependency_overrides.update(
        {
            get_auth_store: lambda: store,
            get_orchestrator: lambda: scripted_orchestrator(tmp),
            get_user_rate_limiter: lambda: RequestRateLimiter(max_per_minute=100),
            get_ip_rate_limiter: lambda: RequestRateLimiter(max_per_minute=100),
            get_user_budget_tracker: lambda: DailyBudgetTracker(tmp / "budget.json"),
        }
    )
    try:
        with TestClient(app) as client:
            step_1_the_routes(client)
            step_2_cheap_health_checks(client)
            step_3_no_login_no_answer(client)
            key = step_4_invite_to_key(client, store)
            step_5_the_live_stream(client, key)
            step_6_rate_limits(client, key)
    finally:
        app.dependency_overrides.clear()
    step_7_the_ci_pipeline()
    step_8_the_eval_gate()
    print("\nDone. The app, logins, limits and stream were real; Claude's replies were scripted.")


if __name__ == "__main__":
    main()
