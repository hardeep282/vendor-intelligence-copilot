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

    # Day 8, Addendum A2 §1.1: if the primary model (whatever the caller's prompt.yaml names)
    # exhausts its own retries, LLMClient routes one more attempt to this model before giving
    # up. None (the default) means no fallback -- a primary-model outage surfaces as an error,
    # same as every day before this one. Verify the exact current model id before setting this
    # in a real environment; left unset in .env.example on purpose (ADR-005 already names the
    # primary; a fallback is an operational choice, not a code default).
    fallback_model: str | None = None

    # Spend control: a global daily cap in USD enforced by the input gate (Day 7).
    daily_spend_cap_usd: float = Field(default=5.0, gt=0)
    # Input gate (Day 7 step 6): per-role requests/minute, max question length, and a kill
    # switch that blocks every request regardless of anything else -- the one knob an operator
    # flips first in an incident, before touching anything more surgical.
    rate_limit_per_minute: int = Field(default=30, gt=0)
    max_question_chars: int = Field(default=4000, gt=0)
    kill_switch_enabled: bool = False

    # Day 8, A2 §1.6: per-identity (API key) and per-client-IP request limits, on top of the
    # per-role limit above -- see copilot.api.rate_limit's module docstring for why a per-role
    # limit alone isn't enough once requests carry an identity. Also a per-identity daily cost
    # budget, independent of (and tighter than) InputGate's global per-role daily_spend_cap_usd
    # above -- one noisy caller's key should hit its own ceiling well before it could ever push
    # the shared role-wide cap.
    per_user_rate_limit_per_minute: int = Field(default=20, gt=0)
    per_ip_rate_limit_per_minute: int = Field(default=60, gt=0)
    per_user_daily_budget_usd: float = Field(default=1.0, gt=0)

    # Day 8 step 7: the orchestrator's checkpoint store. None (the default -- every local dev
    # setup and every test) means `copilot.api.dependencies.get_orchestrator` falls back to the
    # existing local SQLite file; a real DSN (e.g.
    # "postgresql://user:pass@host:5432/copilot") switches it to a `PostgresSaver` over that
    # Postgres instance instead, so checkpoint state survives a redeploy or a container restart
    # rather than living on one container's local disk. A `SecretStr` because the DSN carries a
    # password.
    checkpoint_database_url: SecretStr | None = None

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
