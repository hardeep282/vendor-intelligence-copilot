"""Print the exact grounding data InsightService hands the model for one vendor.

Purpose : a mechanical way to check an InsightService narrative, instead of trusting it by eye
          or the model's own `key_metrics_cited` claims. This makes NO LLM call (zero cost) --
          it just runs the same `gather_vendor_data()` lookup the service uses, then prints each
          raw field so it can be diffed against a narrative you already have in hand.
Usage   : uv run python scripts/verify_vendor_data.py "DIAGEO NORTH AMERICA INC" [--role viewer]
"""

from __future__ import annotations

import argparse
import sys

from copilot.data import store
from copilot.guardrails.policy import load_policy
from copilot.insights.service import VendorNotFoundError, gather_vendor_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vendor_name")
    parser.add_argument("--role", default="viewer")
    args = parser.parse_args()

    con = store.connect()
    policy = load_policy()
    try:
        data = gather_vendor_data(con, args.vendor_name, policy, role=args.role)
    except VendorNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Raw grounding data for {args.vendor_name!r} (role={args.role}):")
    print("This is EXACTLY what InsightService hands the model -- nothing more, nothing less.")
    print()
    for table, fields in data.items():
        print(f"[{table}]")
        for field, value in fields.items():
            print(f"  {field} = {value!r}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
