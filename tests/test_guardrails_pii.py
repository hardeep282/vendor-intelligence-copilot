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


# -- 30 Oct 2026: Presidio narrowed to personal identifiers --------------------------------
# A real laptop run (full Presidio + en_core_web_lg) flagged a vendor-level forecast answer as
# DATE_TIME, URL and US_DRIVER_LICENSE x3, escalating a clean answer. These tests pin the fix.

_FORECAST_ANSWER = (
    "portfolio demand forecast (naive chosen by WAPE): next 3 month(s) = "
    "[3758005.0, 3758005.0, 3758005.0]. I could compute vendor-level controllable leakage "
    "(vendor_profit_leakage.ControllableLeakage) but not the SKU breakdown. Forecast for next "
    "quarter. DIAGEO NORTH AMERICA INC had $68,739,834.97 revenue; JIM BEAM BRANDS follows."
)


def test_business_answer_with_forecast_numbers_has_no_pii() -> None:
    """Whichever layer runs (Presidio or the regex fallback), a vendor-level answer with dates,
    dotted table names, 7-digit forecasts and vendor names must come back clean."""
    from copilot.guardrails.pii import find_pii

    assert find_pii(_FORECAST_ANSWER) == []


def test_real_personal_identifiers_are_still_found() -> None:
    from copilot.guardrails.pii import find_pii

    found = {
        e.entity_type for e in find_pii("Email jane.doe@example.com, card 4111 1111 1111 1111.")
    }
    assert "EMAIL_ADDRESS" in found
    assert "CREDIT_CARD" in found


def test_presidio_is_called_with_the_entity_allowlist_and_threshold(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Pins the call shape without needing Presidio installed: a fake analyzer records the
    arguments `find_pii` passes."""
    from copilot.guardrails import pii

    calls: list[dict[str, object]] = []

    class _FakeAnalyzer:
        def analyze(self, **kwargs: object) -> list[object]:
            calls.append(kwargs)
            return []

    monkeypatch.setattr(pii, "_get_analyzer", lambda: _FakeAnalyzer())
    assert pii.find_pii("anything") == []
    assert calls[0]["entities"] == pii.PRESIDIO_ENTITIES
    assert calls[0]["score_threshold"] == pii.PRESIDIO_SCORE_THRESHOLD
    assert "US_DRIVER_LICENSE" not in pii.PRESIDIO_ENTITIES
    assert "DATE_TIME" not in pii.PRESIDIO_ENTITIES
    assert "PERSON" not in pii.PRESIDIO_ENTITIES
