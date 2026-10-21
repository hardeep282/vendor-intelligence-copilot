"""Tests for copilot.api.auth: invite-code redemption and API-key authentication. Each test
builds its own `AuthStore` against a `tmp_path` file, same isolation convention
`tests/test_input_gate.py` uses for its own file-backed trackers -- no test ever touches
`DEFAULT_AUTH_STORE_PATH`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot.api.auth import AuthStore, InvalidCredential


def _store(tmp_path: Path) -> AuthStore:
    return AuthStore(tmp_path / "auth_store.json")


def test_admin_issued_api_key_authenticates_with_its_role(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = store.issue_api_key(role="analyst", label="ci-bot")

    principal = store.authenticate(key)

    assert principal.role == "analyst"
    assert principal.label == "ci-bot"
    assert principal.key_id  # non-empty, stable identity for rate limiting


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.issue_api_key(role="viewer", label="someone")

    with pytest.raises(InvalidCredential):
        store.authenticate("not-a-real-key-at-all")


def test_invite_code_redeems_once_for_an_api_key_of_its_role(tmp_path: Path) -> None:
    store = _store(tmp_path)
    invite = store.issue_invite(role="viewer", label="new hire")

    key = store.redeem_invite(invite, label="priya")
    principal = store.authenticate(key)

    assert principal.role == "viewer"
    assert principal.label == "priya"


def test_an_invite_code_cannot_be_redeemed_twice(tmp_path: Path) -> None:
    store = _store(tmp_path)
    invite = store.issue_invite(role="viewer", label="new hire")
    store.redeem_invite(invite, label="first redeemer")

    with pytest.raises(InvalidCredential):
        store.redeem_invite(invite, label="second redeemer")


def test_an_unknown_invite_code_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvalidCredential):
        store.redeem_invite("totally-made-up-code", label="x")


def test_two_issued_keys_get_different_key_ids(tmp_path: Path) -> None:
    """key_id is the rate-limit/budget bucket -- two distinct keys must never collide onto it."""
    store = _store(tmp_path)
    key_a = store.authenticate(store.issue_api_key(role="viewer", label="a"))
    key_b = store.authenticate(store.issue_api_key(role="viewer", label="b"))

    assert key_a.key_id != key_b.key_id


def test_raw_key_is_never_written_to_the_store_file(tmp_path: Path) -> None:
    """The one thing this module's whole design exists to guarantee -- a stolen store file
    must not hand over a usable credential."""
    path = tmp_path / "auth_store.json"
    store = AuthStore(path)
    key = store.issue_api_key(role="admin", label="root")

    assert key not in path.read_text(encoding="utf-8")
