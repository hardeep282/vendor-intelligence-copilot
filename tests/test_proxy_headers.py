"""The client address the app sees behind nginx (per-IP rate limiting depends on it).

uvicorn runs with `--proxy-headers --forwarded-allow-ips "*"` (docker/api.Dockerfile), so it
replaces the connection's address with the one in X-Forwarded-For. uvicorn's deployment docs
warn that trusting "*" is only safe when the proxy overwrites that header. These tests pin
both halves: nginx overwrites (infra/server/user-data.sh), and what uvicorn then does with a
header that was overwritten vs. one that was appended to (the 9 Nov 2026 finding).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_BOOTSTRAP = REPO_ROOT / "infra" / "server" / "user-data.sh"
DOCKERFILE = REPO_ROOT / "docker" / "api.Dockerfile"

DOCKER_GATEWAY = "172.17.0.1"  # how nginx on the host reaches the container
REAL_CLIENT = "203.0.113.9"  # documentation-range address standing in for a real visitor
FAKE_CLIENT = "6.6.6.6"  # what a visitor might put in its own X-Forwarded-For


def _seen_client_host(forwarded_for: str, trusted: str = "*") -> str:
    """Run one request through uvicorn's proxy-headers middleware; return the client host the
    app would see as `request.client.host`."""
    seen: dict[str, Any] = {}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen["client"] = scope["client"]

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=trusted)  # type: ignore[arg-type]
    scope = {
        "type": "http",
        "scheme": "http",
        "client": (DOCKER_GATEWAY, 51000),
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))  # type: ignore[arg-type]
    return str(seen["client"][0])


def test_nginx_overwrites_x_forwarded_for() -> None:
    config = NGINX_BOOTSTRAP.read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in config
    assert "$proxy_add_x_forwarded_for" not in config  # appending keeps the client's own value


def test_uvicorn_still_trusts_proxy_headers() -> None:
    """The other half: without --proxy-headers every request would look like it came from
    nginx, and the per-IP limit would throttle all visitors together."""
    cmd = DOCKERFILE.read_text(encoding="utf-8")
    assert '"--proxy-headers"' in cmd
    assert '"--forwarded-allow-ips"' in cmd


def test_overwritten_header_gives_the_real_client() -> None:
    # What nginx sends now: only the address it actually saw.
    assert _seen_client_host(REAL_CLIENT) == REAL_CLIENT


def test_appended_header_would_let_a_client_fake_its_address() -> None:
    """Why the overwrite matters: with the old `$proxy_add_x_forwarded_for`, nginx passed on
    "<whatever the client sent>, <real address>", and uvicorn trusting "*" picks the fake."""
    appended = f"{FAKE_CLIENT}, {REAL_CLIENT}"
    assert _seen_client_host(appended) == FAKE_CLIENT
    # Trusting only the gateway would also have defended against it.
    assert _seen_client_host(appended, trusted=DOCKER_GATEWAY) == REAL_CLIENT
