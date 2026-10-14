"""Tests for LangSmith trace masking (Day 7 step 7). `mask_run_payload` is tested directly
(the pure function `LLMClient.complete`/`.structured` pass as `process_inputs`/`process_outputs`
-- see that module's docstring for why a decorator-level function, not a live `Client`, was the
right call), rather than through a real traced LLM call: exercising the masking logic doesn't
need a LangSmith connection, and this project never puts a real API key in this chat/session.
"""

from __future__ import annotations

from copilot.guardrails.trace_masking import RESTRICTED_PAYLOAD_MARKER, mask_run_payload


def test_clean_payload_passes_through_unmasked() -> None:
    payload = {"question": "What is our top vendor's fill rate?", "role": "analyst"}
    assert mask_run_payload(payload) == payload


def test_email_in_a_string_value_is_redacted() -> None:
    masked = mask_run_payload({"answer": "contact jane.doe@example.com for details"})
    assert "jane.doe@example.com" not in masked["answer"]
    assert "[REDACTED:EMAIL_ADDRESS]" in masked["answer"]


def test_secret_in_a_string_value_is_redacted() -> None:
    masked = mask_run_payload({"system": "key is sk-ant-abcdefghijklmnopqrstuvwxyz"})
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz" not in masked["system"]
    assert "[REDACTED:anthropic_api_key]" in masked["system"]


def test_masking_recurses_into_nested_dicts_and_lists() -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "email me at a@b.com"},
            {"role": "assistant", "content": "sure, noted"},
        ]
    }
    masked = mask_run_payload(payload)
    assert "a@b.com" not in masked["messages"][0]["content"]
    assert masked["messages"][1]["content"] == "sure, noted"


def test_non_string_values_pass_through_unchanged() -> None:
    payload = {"max_tokens": 1024, "effort": "high", "cache_system": True, "nothing": None}
    assert mask_run_payload(payload) == payload


def test_a_restricted_table_name_hides_the_whole_payload() -> None:
    payload = {
        "system": "Schema card includes vw_PortfolioHealth.",
        "messages": [{"role": "user", "content": "what's in it?"}],
    }
    masked = mask_run_payload(payload)
    assert masked == {"_masked": RESTRICTED_PAYLOAD_MARKER}
    # The rest of the payload (the user's own message, unrelated to the restricted name) is
    # also gone -- "hidden restricted payloads" means the whole thing, not selective redaction.
    assert "what's in it?" not in str(masked)


def test_a_restricted_table_name_nested_in_a_list_still_hides_everything() -> None:
    payload = {"messages": [{"role": "system", "content": "...vw_CleanAnalysis..."}]}
    assert mask_run_payload(payload) == {"_masked": RESTRICTED_PAYLOAD_MARKER}


def test_an_unrelated_question_about_a_restricted_sounding_word_is_not_hidden() -> None:
    """Sanity check against over-matching: a question that merely mentions the general idea of
    restricted data, without actually naming one of the policy's specific restricted tables/
    views, should pass through normally.
    """
    payload = {"question": "Which views are considered restricted in our data policy?"}
    assert mask_run_payload(payload) == payload
