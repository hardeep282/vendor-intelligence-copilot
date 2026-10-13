"""FastAPI application: the HTTP entry point of the Copilot.

Purpose : Day 2 walking skeleton. /health says the process is alive; /version says exactly
          which build is deployed. Later days add /ask behind auth.
Inputs  : settings from the environment (.env locally); in prod, secrets from SSM at start-up.
Outputs : JSON responses.
Run     : uv run uvicorn copilot.api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version

from fastapi import FastAPI
from pydantic import BaseModel

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
