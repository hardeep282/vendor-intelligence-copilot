"""Fakes for the Anthropic SDK's streaming Messages API, used only by tests.

Purpose : exercise copilot.llm.client's retry, repair, TTFT and cost logic without a network
          call or a real API key -- LLM calls that need real keys run on the user's machine
          (docs/HANDOFF.md: "keys never go in chat").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeEvent:
    type: str


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 20
    cache_creation_input_tokens: int | None = 0
    cache_read_input_tokens: int | None = 0


@dataclass
class FakeTextBlock:
    text: str = ""
    parsed_output: Any = None
    type: str = "text"


@dataclass
class FakeMessage:
    content: list[FakeTextBlock]
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_reason: str = "end_turn"


class FakeStream:
    """Stands in for the `with client.messages.stream(...) as stream:` context manager."""

    def __init__(self, events: list[FakeEvent], final: FakeMessage) -> None:
        self._events = events
        self._final = final

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __iter__(self) -> Any:
        return iter(self._events)

    def get_final_message(self) -> FakeMessage:
        return self._final


class FakeMessagesResource:
    """Stands in for `anthropic.Anthropic(...).messages`.

    `responses` is a queue: each `.stream()` call pops one item, which is either
    `(events, final_message)` or an `Exception` instance to raise instead.
    """

    def __init__(self, responses: list[tuple[list[FakeEvent], FakeMessage] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeMessagesResource ran out of queued responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        events, final = item
        return FakeStream(events, final)


def text_response(text: str, **usage_kwargs: Any) -> tuple[list[FakeEvent], FakeMessage]:
    """A plain-text happy-path response: one content_block_delta event, then the final message."""
    return (
        [FakeEvent("message_start"), FakeEvent("content_block_delta"), FakeEvent("message_stop")],
        FakeMessage(content=[FakeTextBlock(text=text)], usage=FakeUsage(**usage_kwargs)),
    )


def structured_response(
    parsed_output: Any, **usage_kwargs: Any
) -> tuple[list[FakeEvent], FakeMessage]:
    """A structured-output happy-path response, as `output_format=...` would return it."""
    return (
        [FakeEvent("message_start"), FakeEvent("content_block_delta"), FakeEvent("message_stop")],
        FakeMessage(
            content=[FakeTextBlock(text="", parsed_output=parsed_output)],
            usage=FakeUsage(**usage_kwargs),
        ),
    )
