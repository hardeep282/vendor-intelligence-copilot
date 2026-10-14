"""Tests for the PII regex fallback (Day 7 step 2). Tests `_regex_entities` directly rather than
`find_pii` for determinism: `find_pii` prefers Presidio when it's installed and its spaCy model
is available, which varies by environment (see `pii.py`'s own module docstring) -- the regex
layer is what's guaranteed to run everywhere, including in CI, so it's what gets exact-match
assertions. `test_guardian.py` exercises `find_pii` itself (whichever backend fires) through the
Guardian's own contract instead.
"""

from __future__ import annotations

from copilot.guardrails.pii import _regex_entities


def test_finds_email() -> None:
    entities = _regex_entities("contact jane.doe@example.com for details")
    assert any(
        e.entity_type == "EMAIL_ADDRESS" and e.text == "jane.doe@example.com" for e in entities
    )


def test_finds_phone() -> None:
    entities = _regex_entities("call 555-123-4567 tomorrow")
    assert any(e.entity_type == "PHONE_NUMBER" for e in entities)


def test_source_is_regex_fallback() -> None:
    entities = _regex_entities("email me at a@b.com")
    assert all(e.source == "regex_fallback" for e in entities)


def test_clean_text_finds_nothing() -> None:
    assert _regex_entities("Revenue grew 12% versus last quarter.") == []
