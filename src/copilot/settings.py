"""Central application settings.

Purpose : one typed place for every configuration value and secret.
Inputs  : environment variables and an optional local `.env` file (never committed).
Outputs : a cached `Settings` object via `get_settings()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed settings. Secrets use SecretStr so they never print in logs or reprs."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"

    # LLM provider (Day 3 onwards). Optional so tests and the data layer run without keys.
    anthropic_api_key: SecretStr | None = None

    # LangSmith tracing (Day 2 sets the same variables on the server).
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "vendor-copilot-dev"

    # Spend control: a global daily cap in USD enforced by the input gate (Day 7).
    daily_spend_cap_usd: float = Field(default=5.0, gt=0)
    # Input gate (Day 7 step 6): per-role requests/minute, max question length, and a kill
    # switch that blocks every request regardless of anything else -- the one knob an operator
    # flips first in an incident, before touching anything more surgical.
    rate_limit_per_minute: int = Field(default=30, gt=0)
    max_question_chars: int = Field(default=4000, gt=0)
    kill_switch_enabled: bool = False

    # Build metadata: the Git commit baked into the image by CI (shown by /version).
    git_sha: str = "dev"

    # AWS. In prod, secrets live in SSM Parameter Store under `ssm_prefix` (ADR-004).
    aws_region: str = "ap-south-1"
    ssm_prefix: str = "/vendor-copilot/prod"

    # Data layer.
    snapshot_dir: Path = REPO_ROOT / "data" / "snapshot"
    # Minimum aggregation threshold: no figure may be built from fewer than k SKUs.
    min_aggregation_k: int = Field(default=5, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings object (parsed once)."""
    return Settings()
