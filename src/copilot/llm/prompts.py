"""Versioned prompt loader: prompt text lives in YAML, not buried in Python strings.

Purpose : one reviewable, versioned file per prompt (`prompts/<name>/v<N>.yaml`), so a prompt
          change is a diff to that file -- visible in `git log`, picked up by eval history --
          instead of a string edit lost inside a service method.
Inputs  : a prompt name and (optionally) a version; `prompts/<name>/v<N>.yaml` on disk.
Outputs : a validated `Prompt`, with `.render_system()` / `.render_user()` for the final text.

A behaviour change (tone, grounding rule, output shape) is a NEW version file, not an edit to
an existing one, so whatever a past eval run scored stays attached to the version it scored.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from copilot.settings import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class PromptNotFoundError(FileNotFoundError):
    """Raised when no YAML file exists for the requested prompt name/version."""


class Prompt(BaseModel):
    """One versioned prompt: everything an `LLMClient` call needs except the runtime inputs."""

    name: str
    version: int = Field(gt=0)
    model: str
    max_tokens: int = Field(gt=0)
    effort: Effort | None = None
    cache_system: bool = False
    system: str
    user_template: str

    def render_system(self, **kwargs: object) -> str:
        return self.system.format(**kwargs)

    def render_user(self, **kwargs: object) -> str:
        return self.user_template.format(**kwargs)


def _dir_for(name: str) -> Path:
    return PROMPTS_DIR / name


def _path_for(name: str, version: int) -> Path:
    return _dir_for(name) / f"v{version}.yaml"


def _latest_version(name: str) -> int:
    folder = _dir_for(name)
    versions = [int(p.stem[1:]) for p in folder.glob("v*.yaml") if p.stem[1:].isdigit()]
    if not versions:
        raise PromptNotFoundError(f"no prompt files under {folder}")
    return max(versions)


@cache
def load_prompt(name: str, version: int | None = None) -> Prompt:
    """Load and validate one prompt file. Cached: prompts don't change mid-process, and an
    on-disk edit is picked up on the next process restart, same as any other config file.
    """
    v = version if version is not None else _latest_version(name)
    path = _path_for(name, v)
    if not path.exists():
        raise PromptNotFoundError(str(path))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    prompt = Prompt.model_validate(raw)
    if prompt.name != name or prompt.version != v:
        raise PromptNotFoundError(
            f"{path} declares name={prompt.name!r} version={prompt.version} "
            f"but was loaded as name={name!r} version={v}"
        )
    return prompt


__all__ = ["Effort", "Prompt", "PromptNotFoundError", "load_prompt"]
