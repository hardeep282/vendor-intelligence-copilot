"""Day 7 step 2: PII detection for the Guardian's `_check_pii`/`_apply_redactions`.

Purpose : find personally-identifying spans in a piece of text. Presidio (master prompt C4's
          named tool) when it's installed and its spaCy model is available; a small, dependency-
          free regex fallback otherwise, so the Guardian's PII check never silently no-ops just
          because a model download failed in this environment.
Inputs  : a string (the Orchestrator's drafted answer).
Outputs : a list of `PiiEntity` (type, matched text, source) -- `guardian.py` turns each into a
          Finding and a redaction.

**Why a fallback instead of making Presidio a hard dependency:** this project's own snapshot and
synthetic knowledge corpus contain no real personal data (ADR-002, R1 in RAID.md) -- the
licence-safe Gold snapshot is vendor-level aggregates, and the Day 4 contracts are explicitly
labelled synthetic. Presidio's spaCy model (`en_core_web_lg`, ~560MB) is a real, slow install
this build workspace cannot reliably fetch (see `docs/BUILD_LOG.md`'s existing R9-style network
notes); `train_risk_classifier.py`/`build_rag_index.py` already establish the convention of
"real heavy dependency runs on your machine" for exactly this reason. The regex fallback below
is not a toy: it is the layer that actually runs in every test and every CI job, so the PII
check has real, committed coverage (`tests/test_guardrails_pii.py`) rather than skipped tests
behind an optional import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_REGEX_PATTERNS = {
    "EMAIL_ADDRESS": _EMAIL,
    "PHONE_NUMBER": _PHONE,
    "CREDIT_CARD": _CREDIT_CARD,
}


@dataclass(frozen=True)
class PiiEntity:
    entity_type: str
    text: str
    source: str  # "presidio" or "regex_fallback"


#: Presidio entity types this Guardian looks for (30 Oct 2026). With no `entities` argument,
#: Presidio runs every recognizer it has, and on this project's business text that produced
#: only false positives on a real laptop run: DATE_TIME on "next quarter", URL on
#: "vendor_profit_leakage.ControllableLeakage", US_DRIVER_LICENSE (score 0.01) on the forecast
#: value 3758005. The data here is vendor-level aggregates with no people in it (ADR-002), so
#: the check is narrowed to identifiers that are personal by construction. PERSON is left out
#: on purpose: vendor names such as "JIM BEAM BRANDS" read as personal names to an NER model.
PRESIDIO_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "UK_NHS",
]

#: Presidio's own confidence floor. 0.4 keeps its phone recognizer (which scores 0.4) and
#: every checksum-validated hit (cards, IBANs, NHS numbers score 1.0), while dropping the
#: weak pattern guesses that scored 0.01-0.3 in the false-positive run above.
PRESIDIO_SCORE_THRESHOLD = 0.4

_analyzer_cache: object | None = None
_analyzer_unavailable = False


def _get_analyzer() -> object | None:
    """Builds the Presidio `AnalyzerEngine` (which loads the spaCy model) at most once per
    process -- construction is the slow part (a model load), `analyze()` calls on an existing
    instance are fast. A failed build is cached too (`_analyzer_unavailable`), so a missing
    model doesn't re-attempt and re-fail on every single call.
    """
    global _analyzer_cache, _analyzer_unavailable
    if _analyzer_unavailable:
        return None
    if _analyzer_cache is not None:
        return _analyzer_cache
    try:
        from presidio_analyzer import AnalyzerEngine

        _analyzer_cache = AnalyzerEngine()
    except Exception:  # noqa: BLE001 -- ImportError (not installed) or a missing spaCy model
        # raising deep inside Presidio's own init path with varied exception types across
        # versions; either way means "fall back to regex", never "crash the Guardian".
        _analyzer_unavailable = True
        return None
    return _analyzer_cache


def _presidio_entities(text: str) -> list[PiiEntity] | None:
    """Returns None (not []) when Presidio/its model aren't usable here, so `find_pii` knows to
    fall back rather than reporting a clean scan that never actually ran.
    """
    analyzer = _get_analyzer()
    if analyzer is None:
        return None
    try:
        results = analyzer.analyze(  # type: ignore[attr-defined]
            text=text,
            language="en",
            entities=PRESIDIO_ENTITIES,
            score_threshold=PRESIDIO_SCORE_THRESHOLD,
        )
    except Exception:  # noqa: BLE001 -- an analysis-time failure also falls back to regex
        # rather than crashing the Guardian; the engine itself stays cached for next time.
        return None
    return [
        PiiEntity(entity_type=r.entity_type, text=text[r.start : r.end], source="presidio")
        for r in results
    ]


def _regex_entities(text: str) -> list[PiiEntity]:
    entities: list[PiiEntity] = []
    for entity_type, pattern in _REGEX_PATTERNS.items():
        for m in pattern.finditer(text):
            entities.append(
                PiiEntity(entity_type=entity_type, text=m.group(0), source="regex_fallback")
            )
    return entities


def find_pii(text: str) -> list[PiiEntity]:
    """Presidio's result when it ran successfully, otherwise the regex fallback. Never both --
    a caller comparing `source` can tell which layer actually produced a given hit.
    """
    presidio_result = _presidio_entities(text)
    if presidio_result is not None:
        return presidio_result
    return _regex_entities(text)


__all__ = ["PRESIDIO_ENTITIES", "PRESIDIO_SCORE_THRESHOLD", "PiiEntity", "find_pii"]
