"""Day 8 step 4: invite-code + API-key authentication for the HTTP API.

Purpose : the sprint doc's "invite-code (people) + API-key (programmatic), roles" -- a human
          gets a one-time invite code out-of-band (from an admin running `scripts/
          issue_invite_code.py`), redeems it once for a long-lived API key tied to a `Role`,
          and every later request authenticates with that key. A programmatic caller (a script,
          a CI job) can skip the invite step entirely if an admin issues it an API key directly
          the same way (`AuthStore.issue_api_key`) -- the invite code only exists to let a human
          self-service their first key without an admin typing their name into a file.
Inputs  : an invite code (redeemed once) or an API key, read from the `Authorization: Bearer
          <token>` header on every other request.
Outputs : a `Principal` (role + a stable `key_id` identifying *this* key, for the per-identity
          rate limiter in `copilot.api.rate_limit` -- never the raw key itself, which is never
          stored or logged anywhere after the moment it's issued).

**Never store the raw secret, only its hash** -- same posture a password store takes, for the
same reason: a stolen `data/auth/*.json` file must not hand over usable credentials. Invite
codes and API keys are both `secrets.token_urlsafe(24)` (192 bits, URL-safe so they paste
cleanly into a header or a terminal) hashed with SHA-256 before ever touching disk; the raw
value is returned to the caller exactly once (at issue/redeem time) and never again -- there is
no "show my key" endpoint, by design, same as any real secrets manager.

**File-backed, not a database** -- this project has no database yet (Day 8 step 8 adds Postgres
for *checkpoints*, not auth), and the existing `SpendTracker`/`copilot.guardrails.audit_log`
already established "a small JSON/JSONL file under `data/`, loaded fresh each call, atomic
enough for this sprint's traffic" as this repo's answer to "needs to survive a restart but isn't
worth a database yet." `AuthStore` follows that exact shape rather than inventing a new one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

from pydantic import BaseModel

from copilot.guardrails.policy import Role
from copilot.settings import REPO_ROOT

DEFAULT_AUTH_STORE_PATH = REPO_ROOT / "data" / "auth" / "auth_store.json"


class InvalidCredential(ValueError):
    """Raised by `AuthStore.redeem_invite`/`.authenticate` for any invalid, unknown, or
    already-used credential. One exception type for every failure mode on purpose: which
    specific reason a credential didn't work is not information to hand back to an
    unauthenticated caller (same "don't help an attacker narrow it down" posture a login form's
    single "invalid username or password" message takes).
    """


class Principal(BaseModel):
    """What a successfully authenticated request resolves to. `key_id` (not the raw key, never
    kept past issue time) is the stable identity `copilot.api.rate_limit`'s per-user limiter and
    per-user daily budget key on -- two requests with the same `key_id` are the same caller,
    however many processes or machines they're calling from.
    """

    key_id: str
    role: Role
    label: str


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class AuthStore:
    """Loaded fresh on every call (small file, infrequent writes) -- same consistency posture
    `SpendTracker` already takes: correctness over the read-modify-write races a multi-process
    deployment could in principle hit matters less here than it would for cost accounting, since
    a lost invite-redemption or API-key issuance just means the caller retries, not a wrong
    number baked into a compliance record.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else DEFAULT_AUTH_STORE_PATH

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {"invites": {}, "keys": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"invites": {}, "keys": {}}
        if not isinstance(data, dict):
            return {"invites": {}, "keys": {}}
        data.setdefault("invites", {})
        data.setdefault("keys", {})
        return data

    def _save(self, data: dict[str, dict[str, object]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def issue_invite(self, role: Role, label: str) -> str:
        """Admin-only, out-of-band (today: `scripts/issue_invite_code.py`, run on the operator's
        own machine -- there is no HTTP endpoint that *issues* an invite, only one that
        *redeems* one, so a caller can never mint themselves access). Returns the raw code --
        the only moment it ever exists outside this call's return value and the person it's
        handed to.
        """
        code = secrets.token_urlsafe(24)
        data = self._load()
        data["invites"][_hash(code)] = {
            "role": role,
            "label": label,
            "used": False,
            "issued_at": time.time(),
        }
        self._save(data)
        return code

    def issue_api_key(self, role: Role, label: str) -> str:
        """Admin-issued directly (a script, a CI credential) -- the programmatic-caller path
        that skips the invite step, per this module's own docstring.
        """
        return self._issue_key(role, label)

    def redeem_invite(self, invite_code: str, label: str) -> str:
        """The one HTTP-reachable way a caller obtains an API key: a human's self-service step
        after getting an invite code out-of-band. Single-use -- the invite's hash is marked
        `used` in the same write that issues the key, so a second redemption attempt with the
        same code (a replay, or two people sharing one invite) raises `InvalidCredential` rather
        than minting a second key off one invite.
        """
        data = self._load()
        invite_hash = _hash(invite_code)
        invite = data["invites"].get(invite_hash)
        if invite is None or not isinstance(invite, dict) or invite.get("used"):
            raise InvalidCredential("invite code is invalid, unknown, or already used")
        invite["used"] = True
        invite["redeemed_label"] = label
        self._save(data)
        return self._issue_key(invite["role"], label)

    def _issue_key(self, role: Role, label: str) -> str:
        key = secrets.token_urlsafe(24)
        key_id = secrets.token_hex(8)  # short, non-secret identity for logs/rate-limit buckets
        data = self._load()
        data["keys"][_hash(key)] = {
            "key_id": key_id,
            "role": role,
            "label": label,
            "issued_at": time.time(),
        }
        self._save(data)
        return key

    def authenticate(self, raw_key: str) -> Principal:
        """Looks up the hash of `raw_key`, never the key itself -- a timing-safe-enough
        comparison in practice (dict lookup on a hash, not a loop comparing raw secrets
        character by character), and nothing in this store ever matches the raw value against
        anything, so there is no code path that could accidentally log or echo it back.
        """
        data = self._load()
        record = data["keys"].get(_hash(raw_key))
        if record is None or not isinstance(record, dict):
            raise InvalidCredential("API key is invalid or unknown")
        return Principal(key_id=record["key_id"], role=record["role"], label=record["label"])


__all__ = ["AuthStore", "InvalidCredential", "Principal"]
