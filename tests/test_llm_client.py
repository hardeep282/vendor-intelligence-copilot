"""copilot.llm.client: retries, repair loop, TTFT/cost metrics -- all against a fake SDK.

No network call and no API key is used anywhere in this file (see docs/HANDOFF.md: real LLM
calls run on the user's machine with dev keys, not here). `time.sleep` is patched out so the
retry tests run instantly instead of waiting out tenacity's real backoff.
"""

from __future__ import annotations

import time

import anthropic
import pytest
from pydantic import BaseModel, Field

from copilot.llm.client import LLMClient
from copilot.llm.types import StructuredOutputError
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response, text_response


class Thing(BaseModel):
    name: str
    score: int = Field(ge=0, le=10)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """tenacity's backoff really sleeps (up to 20s/attempt); skip that in tests."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


def _client_with(responses: list) -> tuple[LLMClient, FakeMessagesResource]:
    client = LLMClient(api_key="sk-test-not-real")
    fake = FakeMessagesResource(responses)
    client._client.messages = fake  # type: ignore[attr-defined]
    return client, fake


def test_complete_happy_path_returns_text_and_metrics() -> None:
    client, fake = _client_with([text_response("hello", input_tokens=50, output_tokens=10)])

    result = client.complete(
        model="claude-haiku-5-5",
        system="be terse",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    assert result.text == "hello"
    assert result.metrics.input_tokens == 50
    assert result.metrics.output_tokens == 10
    assert result.metrics.attempt == 1
    assert result.metrics.cost_usd > 0
    assert result.metrics.ttft_s <= result.metrics.total_latency_s
    assert len(fake.calls) == 1


def test_complete_caches_system_prompt_when_asked() -> None:
    client, fake = _client_with([text_response("ok")])
    client.complete(
        model="claude-haiku-5-5",
        system="long stable system prompt",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        cache_system=True,
    )
    sent_system = fake.calls[0]["system"]
    assert sent_system[0]["cache_control"] == {"type": "ephemeral"}


def test_complete_does_not_send_temperature() -> None:
    """Regression guard: this model generation's API rejects `temperature` (400); never send it."""
    client, fake = _client_with([text_response("ok")])
    client.complete(
        model="claude-sonnet-5",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
    )
    assert "temperature" not in fake.calls[0]
    assert "top_p" not in fake.calls[0]
    assert "top_k" not in fake.calls[0]


def test_complete_sends_effort_via_output_config_when_given() -> None:
    client, fake = _client_with([text_response("ok")])
    client.complete(
        model="claude-sonnet-5",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        effort="low",
    )
    assert fake.calls[0]["output_config"] == {"effort": "low"}


def test_complete_retries_on_rate_limit_then_succeeds() -> None:
    rate_limit = anthropic.RateLimitError(
        message="rate limited", response=_fake_httpx_response(429), body=None
    )
    client, fake = _client_with(
        [rate_limit, text_response("recovered", input_tokens=1, output_tokens=1)]
    )

    result = client.complete(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
    )

    assert result.text == "recovered"
    assert result.metrics.attempt == 2  # first call failed, second (the retry) succeeded
    assert len(fake.calls) == 2


def test_complete_gives_up_after_max_attempts() -> None:
    always_down = anthropic.InternalServerError(
        message="down", response=_fake_httpx_response(500), body=None
    )
    client, fake = _client_with([always_down] * 4)  # stop_after_attempt(4)

    with pytest.raises(anthropic.InternalServerError):
        client.complete(
            model="claude-haiku-5-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        )
    assert len(fake.calls) == 4


def test_complete_does_not_retry_on_bad_request() -> None:
    """A malformed request should fail fast, not burn three retries on a request that can't work."""
    bad = anthropic.BadRequestError(message="bad", response=_fake_httpx_response(400), body=None)
    client, fake = _client_with([bad])

    with pytest.raises(anthropic.BadRequestError):
        client.complete(
            model="claude-haiku-5-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        )
    assert len(fake.calls) == 1


def test_structured_happy_path_validates_and_returns() -> None:
    client, fake = _client_with(
        [structured_response({"name": "x", "score": 5}, input_tokens=5, output_tokens=5)]
    )

    thing, metrics = client.structured(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "give me a Thing"}],
        output_model=Thing,
        max_tokens=50,
    )

    assert thing == Thing(name="x", score=5)
    assert metrics.repair_attempt == 0
    assert len(fake.calls) == 1


def test_structured_repairs_once_on_validation_failure() -> None:
    """Shape-valid JSON (score=99) failing OUR pydantic constraint (score<=10) triggers repair."""
    client, fake = _client_with(
        [
            structured_response({"name": "x", "score": 99}),  # passes SDK schema, fails our model
            structured_response({"name": "x", "score": 5}),  # repaired
        ]
    )

    thing, metrics = client.structured(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "give me a Thing"}],
        output_model=Thing,
        max_tokens=50,
        max_repairs=1,
    )

    assert thing == Thing(name="x", score=5)
    assert metrics.repair_attempt == 1
    assert len(fake.calls) == 2
    # the repair call's conversation grew with the model's bad answer and our correction
    second_call_messages = fake.calls[1]["messages"]
    assert len(second_call_messages) == 3  # original user turn + assistant error + user retry


def test_structured_gives_up_after_max_repairs() -> None:
    client, fake = _client_with(
        [
            structured_response({"name": "x", "score": 99}),
            structured_response({"name": "x", "score": 100}),
        ]
    )

    with pytest.raises(StructuredOutputError):
        client.structured(
            model="claude-haiku-5-5",
            system="s",
            messages=[{"role": "user", "content": "give me a Thing"}],
            output_model=Thing,
            max_tokens=50,
            max_repairs=1,
        )
    assert len(fake.calls) == 2


def test_complete_falls_back_to_configured_model_after_primary_exhausts_retries() -> None:
    """Day 8, A2 §1.1: primary exhausts its 4-attempt budget, client fails over to the
    configured fallback model, which gets its own fresh attempt and succeeds."""
    always_down = anthropic.InternalServerError(
        message="down", response=_fake_httpx_response(500), body=None
    )
    client = LLMClient(api_key="sk-test-not-real", fallback_model="claude-sonnet-5")
    fake = FakeMessagesResource(
        [always_down, always_down, always_down, always_down, text_response("recovered")]
    )
    client._client.messages = fake  # type: ignore[attr-defined]

    result = client.complete(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
    )

    assert result.text == "recovered"
    assert result.metrics.model == "claude-sonnet-5"
    assert result.metrics.used_fallback_model is True
    assert len(fake.calls) == 5  # 4 primary attempts (stop_after_attempt) + 1 fallback attempt
    assert fake.calls[-1]["model"] == "claude-sonnet-5"


def test_complete_raises_primary_error_when_no_fallback_configured() -> None:
    """No fallback_model set (the default): primary exhaustion still raises, unchanged."""
    always_down = anthropic.InternalServerError(
        message="down", response=_fake_httpx_response(500), body=None
    )
    client, fake = _client_with([always_down] * 4)

    with pytest.raises(anthropic.InternalServerError):
        client.complete(
            model="claude-haiku-5-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        )
    assert len(fake.calls) == 4
    assert client._fallback_model is None


def test_structured_falls_back_to_configured_model_after_primary_exhausts_retries() -> None:
    always_down = anthropic.InternalServerError(
        message="down", response=_fake_httpx_response(500), body=None
    )
    client = LLMClient(api_key="sk-test-not-real", fallback_model="claude-sonnet-5")
    fake = FakeMessagesResource(
        [
            always_down,
            always_down,
            always_down,
            always_down,
            structured_response({"name": "x", "score": 5}),
        ]
    )
    client._client.messages = fake  # type: ignore[attr-defined]

    thing, metrics = client.structured(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "give me a Thing"}],
        output_model=Thing,
        max_tokens=50,
    )

    assert thing == Thing(name="x", score=5)
    assert metrics.model == "claude-sonnet-5"
    assert metrics.used_fallback_model is True
    assert len(fake.calls) == 5


def test_complete_does_not_fall_back_when_fallback_equals_primary() -> None:
    """Fallback configured but identical to the primary model: nothing to fail over to."""
    always_down = anthropic.InternalServerError(
        message="down", response=_fake_httpx_response(500), body=None
    )
    client = LLMClient(api_key="sk-test-not-real", fallback_model="claude-haiku-5-5")
    fake = FakeMessagesResource([always_down] * 4)
    client._client.messages = fake  # type: ignore[attr-defined]

    with pytest.raises(anthropic.InternalServerError):
        client.complete(
            model="claude-haiku-5-5",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        )
    assert len(fake.calls) == 4


def test_complete_records_prompt_name_and_version_on_metrics() -> None:
    client, fake = _client_with([text_response("hello")])

    result = client.complete(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        prompt_name="vendor_insight",
        prompt_version=3,
    )

    assert result.metrics.prompt_name == "vendor_insight"
    assert result.metrics.prompt_version == 3
    assert result.metrics.used_fallback_model is False
    assert len(fake.calls) == 1


def test_structured_records_prompt_name_and_version_on_metrics() -> None:
    client, fake = _client_with([structured_response({"name": "x", "score": 5})])

    _, metrics = client.structured(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "give me a Thing"}],
        output_model=Thing,
        max_tokens=50,
        prompt_name="text_to_sql",
        prompt_version=2,
    )

    assert metrics.prompt_name == "text_to_sql"
    assert metrics.prompt_version == 2
    assert len(fake.calls) == 1


def _fake_httpx_response(status_code: int) -> object:
    """A minimal stand-in for the httpx.Response the SDK's errors wrap, with only what their
    __init__ touches (request + status_code)."""
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(status_code=status_code, request=request)
