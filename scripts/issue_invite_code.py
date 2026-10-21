"""Day 8 step 4: admin tooling -- issue a one-time invite code (or an API key directly) outside
the HTTP API.

There is deliberately no HTTP endpoint that *mints* an invite or an API key -- only `POST
/auth/redeem`, which *exchanges* an already-issued invite for a key (`copilot.api.auth`'s own
module docstring: a caller must never be able to grant themselves access). This script is the
other half: run by whoever administers this deployment, on a machine with write access to
`data/auth/auth_store.json` (never committed -- see `.gitignore`).

Usage:
  uv run python scripts/issue_invite_code.py --role viewer --label "jane, procurement team"
  uv run python scripts/issue_invite_code.py --role analyst --label ci-bot --api-key-directly
"""

from __future__ import annotations

import argparse
import sys
from typing import get_args

from copilot.api.auth import AuthStore
from copilot.guardrails.policy import Role

_ROLES = get_args(Role)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=_ROLES)
    parser.add_argument("--label", required=True, help="who/what this is for (free text)")
    parser.add_argument(
        "--api-key-directly",
        action="store_true",
        help="skip the invite step and issue a usable API key immediately (for programmatic "
        "callers -- a script or CI credential -- that have no human to hand an invite to)",
    )
    args = parser.parse_args()

    store = AuthStore()
    if args.api_key_directly:
        key = store.issue_api_key(role=args.role, label=args.label)
        print(f"API key for role={args.role!r} label={args.label!r}:\n  {key}")
        print("\nThis is the only time this key is ever shown. Store it now.")
    else:
        code = store.issue_invite(role=args.role, label=args.label)
        print(f"Invite code for role={args.role!r} label={args.label!r}:\n  {code}")
        print(
            "\nHand this to them to redeem once at POST /auth/redeem "
            '{"invite_code": "...", "label": "..."}. This is the only time it is ever shown.'
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
