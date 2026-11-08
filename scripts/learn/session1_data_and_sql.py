"""Learning script for session 1: the data and SQL layer, step by step.

Purpose : run the real code behind the data and SQL layer in seven small, numbered steps, so you
          can watch it work in VS Code's debugger. No Claude calls: free, no API key, the same
          result every time.
Inputs  : the local snapshot (build it first with `uv run python scripts/build_snapshot.py`).
Outputs : plain-English printout of each step. Nothing is written anywhere.

How to use it in VS Code (see the Code Trail page, chapter 4):
  1. Open this file. Click left of the line numbers to put a red dot on the first line inside
     each `step_...` function you want to watch.
  2. Press F5 and pick "Python Debugger: Current File".
  3. When it pauses, press F10 to go line by line, F11 to step into a function call, and
     watch the Variables panel on the left.
Or just run it: `uv run python scripts/learn/session1_data_and_sql.py`

Added 8 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import duckdb

from copilot.cli import use_utf8_output
from copilot.data import store
from copilot.guardrails.policy import DisclosurePolicy, Role, load_policy
from copilot.sql.examples import retrieve_examples
from copilot.sql.schema import build_schema_card
from copilot.sql.validator import SqlRules, load_rules, validate


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def step_1_open_the_locked_database() -> duckdb.DuckDBPyConnection:
    """Open the snapshot the only way the copilot ever does: read-only, files and network off,
    settings locked (src/copilot/data/store.py, connect)."""
    heading(1, "Open the locked database and list what's in it")
    con = store.connect()
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    for name in tables:
        (rows,) = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone() or (0,)  # noqa: S608
        print(f"  {name:<28} {rows:>6} rows")
    print(f"\n  {len(tables)} tables. Every one is a summary: no product names, brands or prices.")
    return con


def step_2_try_to_break_the_lock(con: duckdb.DuckDBPyConnection) -> None:
    """Three attacks the database itself refuses, even if a query got past the validator."""
    heading(2, "Try to write, read a file, and switch the lock off")
    attacks = {
        "delete data": "DELETE FROM vendor_revenue_summary",
        "read your .env file": "SELECT * FROM read_csv('.env')",
        "turn file access back on": "SET enable_external_access = true",
    }
    for label, sql in attacks.items():
        try:
            con.execute(sql)
            print(f"  !! {label}: NOT refused (this should never happen)")
        except duckdb.Error as exc:
            first_line = str(exc).splitlines()[0][:90]
            print(f"  refused: {label}\n           {first_line}")


def step_3_schema_card_per_role(policy: DisclosurePolicy) -> None:
    """What Claude is told about the database depends on who's asking (sql/schema.py)."""
    heading(3, "The schema card Claude sees, for two different roles")
    for role in ("anonymous", "viewer"):
        card = build_schema_card(policy, role)
        # One line per readable table: "name [data class]: col, col, ..."
        table_lines = [line for line in card.splitlines() if "]:" in line]
        print(f"\n  role = {role}: {len(table_lines)} tables visible")
        for line in table_lines[:4]:
            print(f"    {line[:84]}")
        if len(table_lines) > 4:
            print(f"    ... and {len(table_lines) - 4} more")


def step_4_pick_worked_examples(question: str) -> None:
    """The 3 golden questions sharing the most words with yours (sql/examples.py)."""
    heading(4, "Pick 3 worked examples by word overlap (Jaccard)")
    print(f"  your question: {question!r}")
    for example in retrieve_examples(question, role="viewer", k=3):
        print(f"    {example.id}: {example.question}")


def step_5_validator_on_attacks(policy: DisclosurePolicy, rules: SqlRules) -> None:
    """The six-layer checklist, on the same cases as the session 1 lab (sql/validator.py)."""
    heading(5, "Run the validator on attacks and mistakes")
    cases: list[tuple[Role, str]] = [
        ("analyst", "SELECT * FROM vendor_revenue_summary; DROP TABLE vendor_revenue_summary"),
        ("analyst", "SELECT * FROM read_csv('.env')"),
        ("anonymous", "SELECT VendorName, TotalRevenue FROM vendor_revenue_summary"),
        ("analyst", "SELECT AVG(BlendedMargin) FROM vendor_tiering"),
        (
            "analyst",
            "SELECT SUM(l.TotalFreight) FROM vendor_logistics_cost l "
            "JOIN vendor_monthly_demand d ON l.VendorName = d.VendorName",
        ),
        (
            "analyst",
            "SELECT SUM(MonthlyRevenue) FROM portfolio_monthly_demand WHERE SalesYear = 2025",
        ),
    ]
    for role, sql in cases:
        result = validate(sql, role, policy, rules)
        verdict = "passes" if result.ok else f"BLOCKED: {result.violations[0].code}"
        print(f"  [{role:<9}] {verdict}\n              {sql[:76]}")


def step_6_run_a_good_query(
    con: duckdb.DuckDBPyConnection, policy: DisclosurePolicy, rules: SqlRules
) -> None:
    """A safe query: the validator adds LIMIT 200, then it runs on the locked database."""
    heading(6, "Validate and run a good query")
    sql = (
        "SELECT VendorName, ROUND(TotalRevenue, 2) AS revenue "
        "FROM vendor_revenue_summary ORDER BY revenue DESC"
    )
    result = validate(sql, "analyst", policy, rules)
    print(f"  the SQL that actually runs:\n    {result.sql}")
    for name, revenue in con.execute(result.sql).fetchall()[:3]:
        print(f"    {name:<34} ${revenue:,.2f}")


def step_7_the_k_rule(
    con: duckdb.DuckDBPyConnection, policy: DisclosurePolicy, rules: SqlRules
) -> None:
    """The same question from a viewer and an analyst (the k = 5 filter added 8 Nov 2026)."""
    heading(7, "Same question, two roles: the k = 5 privacy rule")
    sql = "SELECT ROUND(SUM(TotalRevenue), 2) AS total FROM vendor_revenue_summary"
    roles: tuple[Role, ...] = ("analyst", "viewer")
    for role in roles:
        result = validate(sql, role, policy, rules)
        if not result.ok:  # never run a query the validator refused, exactly as the copilot does
            print(f"  {role:<8} BLOCKED: {result.violations[0].code}")
            continue
        (total,) = con.execute(result.sql).fetchone() or (0.0,)
        added = (
            f"  (filter added: {', '.join(result.applied_filters)})"
            if result.applied_filters
            else ""
        )
        print(f"  {role:<8} total revenue ${total:,.2f}{added}")
    small = con.execute(
        "SELECT COUNT(*) FROM vendor_revenue_summary WHERE NOT MeetsMinK"
    ).fetchone()
    print(
        f"\n  {small[0] if small else '?'} vendors have fewer than 5 products, "
        "so a viewer never sees them."
    )


def main() -> None:
    use_utf8_output()
    policy, rules = load_policy(), load_rules()
    con = step_1_open_the_locked_database()
    step_2_try_to_break_the_lock(con)
    step_3_schema_card_per_role(policy)
    step_4_pick_worked_examples("Which vendors have the most controllable leakage?")
    step_5_validator_on_attacks(policy, rules)
    step_6_run_a_good_query(con, policy, rules)
    step_7_the_k_rule(con, policy, rules)
    print("\nDone. Every step above used the copilot's real code, and no AI call was made.")


if __name__ == "__main__":
    main()
