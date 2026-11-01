"""Tests for `copilot.cli.use_utf8_output` (2 Nov 2026): the Windows cp1252 crash fix."""

from __future__ import annotations

import io
import sys

import pytest

from copilot.cli import use_utf8_output


def test_a_cp1252_stream_can_print_symbols_after_the_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real crash: a piped Windows console uses cp1252, which has no "≈"."""
    raw = io.BytesIO()
    cp1252 = io.TextIOWrapper(raw, encoding="cp1252")
    with pytest.raises(UnicodeEncodeError):
        cp1252.write("≈")
    cp1252 = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", cp1252)
    monkeypatch.setattr(sys, "stderr", cp1252)

    use_utf8_output()
    print("EOQ ≈ 120,707 units")
    cp1252.flush()

    assert cp1252.encoding == "utf-8"
    assert "≈".encode() in cp1252.buffer.getvalue()  # type: ignore[attr-defined]


def test_non_text_streams_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = io.StringIO()
    monkeypatch.setattr(sys, "stdout", plain)
    use_utf8_output()  # must not raise
    assert sys.stdout is plain
