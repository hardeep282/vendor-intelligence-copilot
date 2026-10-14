"""Layered SQL validator for LLM-generated queries (Day 3, docs/specs/text_to_sql_safety.md).

Purpose : catch the two different failure families *before* anything runs on the engine:
          (a) structurally unsafe SQL (wrong table, a disguised write, a catalog probe), and
          (b) structurally valid SQL that would still return a wrong NUMBER (a ratio column
          averaged across vendors, a sum after a fan-out join, two overlapping counts added).
          Layer 0 (copilot.data.store) is the last line of defence if this layer is bypassed;
          this layer exists so a bad query is explained and retried instead of silently wrong.
Inputs  : the candidate SQL string, the caller's role, the disclosure policy, the semantic
          rules file (policies/sql_rules.yaml).
Outputs : a `ValidationResult` -- either `ok=True` with the SQL to run (LIMIT applied), or
          `ok=False` with one or more `Violation`s, each carrying the stable `code` the
          self-correction loop (step 4) feeds back to the model and the red-team suite
          (Day 7) asserts against.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import sqlglot
import yaml
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import ParseError

from copilot.guardrails.policy import DisclosurePolicy, Role
from copilot.settings import REPO_ROOT

DEFAULT_RULES_PATH = REPO_ROOT / "policies" / "sql_rules.yaml"
DIALECT = "duckdb"
MAX_LIMIT = 200

# Table-valued functions and catalog probes that must never appear, however they're spelled.
# These read files, the engine's own catalog, or extensions -- never licensed data.
_BLOCKED_FUNCTION_PREFIXES = ("read_", "glob", "duckdb_", "pragma_")
_BLOCKED_SCHEMAS = {"information_schema", "pg_catalog"}
_BLOCKED_STATEMENT_TYPES = (
    exp.Pragma,
    exp.Attach,
    exp.Set,
    exp.Copy,
    exp.Command,  # catches INSTALL/LOAD/CALL, which sqlglot has no dedicated node for
)


class SqlRules(BaseModel):
    version: int
    ratio_columns: list[str]
    fanout_tables: list[str]
    per_vendor_total_columns: list[str]
    non_additive_count_groups: list[list[str]]
    data_coverage: dict[str, list[int]]


def load_rules(path: Path = DEFAULT_RULES_PATH) -> SqlRules:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SqlRules.model_validate(raw)


class Violation(BaseModel):
    code: str
    message: str


class ValidationResult(BaseModel):
    ok: bool
    sql: str  # the (possibly LIMIT-capped) SQL to run when ok, or the original input otherwise
    violations: list[Violation] = []
    truncated: bool = False  # True if a LIMIT was added/lowered to respect MAX_LIMIT


def _cte_names(statement: exp.Expression) -> set[str]:
    return {cte.alias_or_name for cte in statement.find_all(exp.CTE)}


def _function_name(table: exp.Table) -> str | None:
    """Name of the table-valued function `table` calls, or None if it's a plain table ref."""
    func = table.this
    if isinstance(func, exp.Anonymous):
        return str(func.this)  # sqlglot stores the literal called name here, not in sql_name()
    if isinstance(func, exp.Func):
        return func.sql_name()
    return None


def _check_structure(
    statement: exp.Expression, policy: DisclosurePolicy, role: Role
) -> list[Violation]:
    violations: list[Violation] = []

    if not isinstance(statement, exp.Select | exp.Union | exp.Except | exp.Intersect):
        violations.append(
            Violation(code="sql_root_not_select", message="root statement must be SELECT/WITH")
        )
        return violations  # nothing else is safe to inspect

    known_ctes = _cte_names(statement)

    for table in statement.find_all(exp.Table):
        fn = _function_name(table)
        if fn is not None:
            if fn.lower().startswith(_BLOCKED_FUNCTION_PREFIXES):
                violations.append(
                    Violation(
                        code="sql_function_not_allowed",
                        message=f"table function '{fn}' is not allowed",
                    )
                )
            continue  # a function-table has no real table name to check against the policy

        if table.db.lower() in _BLOCKED_SCHEMAS or table.name.lower() in _BLOCKED_SCHEMAS:
            violations.append(
                Violation(code="sql_catalog_access", message=f"'{table.sql()}' is not allowed")
            )
            continue

        name = table.name
        if name in known_ctes:
            continue  # a reference to our own WITH clause, not a real table
        tag = policy.tables.get(name)
        if tag is None:
            violations.append(
                Violation(code="sql_table_not_allowed", message=f"table '{name}' is not allowed")
            )
        elif not policy.can_view(role, tag.data_class):
            violations.append(
                Violation(
                    code="sql_table_not_allowed",
                    message=f"role '{role}' may not read table '{name}'",
                )
            )

    return violations


def _check_cost_limit(statement: exp.Expression) -> list[Violation]:
    """Day 7 red-team case 8 (docs/specs/text_to_sql_safety.md): a multi-table `FROM` with no
    join key and nothing in `WHERE` that bounds it is an unbounded cross join -- block it before
    it ever reaches the engine, rather than relying on the LIMIT cap (`_apply_limit`) alone,
    which bounds the *output* but not the join computation that produces it.

    A join missing `ON`/`USING` is only flagged when `WHERE` also fails to reference columns
    from at least two of the tables involved -- a self-join filtered entirely through `WHERE`
    (no explicit join key) is still bounded, and this project already has one in the golden
    set (`gq-025`'s month-over-month comparison: `FROM portfolio_monthly_demand d,
    portfolio_monthly_demand n WHERE d.SalesMonth = 12 AND n.SalesMonth = 11`), so a blanket
    "every join needs ON/USING" rule would false-block a real, already-validated query.

    **Known limitation, noted rather than silently left undone:** this only sees a `WHERE`
    reference as bounding when the column is table-qualified (`d.SalesMonth`, not bare
    `SalesMonth`) -- sqlglot can't otherwise attribute an unqualified column to one side of the
    join. A comma-join filtered only through unqualified columns is flagged even when it
    happens to be safe; the false-block side of that tradeoff is the one worth taking here.
    """
    if not isinstance(statement, exp.Select):
        return []
    joins = statement.args.get("joins") or []
    unconditioned = [j for j in joins if j.args.get("on") is None and j.args.get("using") is None]
    if not unconditioned:
        return []

    from_expr = statement.args.get("from_")  # sqlglot's own key name, not "from" (a keyword)
    table_refs = list(from_expr.find_all(exp.Table)) if from_expr is not None else []
    for j in unconditioned:
        table_refs.extend(j.find_all(exp.Table))
    aliases = {t.alias_or_name for t in table_refs}

    where = statement.args.get("where")
    where_tables = {c.table for c in where.find_all(exp.Column) if c.table} if where else set()

    if len(aliases & where_tables) < 2:
        return [
            Violation(
                code="sql_cost_limit",
                message="a join with no ON/USING condition, and no WHERE filter bounding at "
                "least two of the joined tables, is an unbounded cross join",
            )
        ]
    return []


def _check_semantics(statement: exp.Expression, rules: SqlRules) -> list[Violation]:
    violations: list[Violation] = []
    ratio_cols = {c.lower() for c in rules.ratio_columns}
    per_vendor_cols = {c.lower() for c in rules.per_vendor_total_columns}
    fanout_tables = {t.lower() for t in rules.fanout_tables}

    group_by = statement.args.get("group") if isinstance(statement, exp.Select) else None
    tables_used = {t.name.lower() for t in statement.find_all(exp.Table)}
    has_fanout_join = bool(tables_used & fanout_tables) and group_by is None

    for agg in statement.find_all(exp.AggFunc):
        cols = [c.name.lower() for c in agg.find_all(exp.Column)]
        if isinstance(agg, exp.Avg | exp.Sum) and any(c in ratio_cols for c in cols):
            violations.append(
                Violation(
                    code="sql_ratio_misuse",
                    message=(
                        f"'{agg.sql()}' averages/sums an already-blended column across rows; "
                        "a portfolio figure must be a ratio of sums instead"
                    ),
                )
            )
        if has_fanout_join and isinstance(agg, exp.Sum) and any(c in per_vendor_cols for c in cols):
            violations.append(
                Violation(
                    code="sql_fanout_sum",
                    message=(
                        f"'{agg.sql()}' sums a per-vendor total after a join against "
                        f"{', '.join(sorted(tables_used & fanout_tables))}, which repeats each "
                        "vendor's row once per month -- aggregate the fan-out table first"
                    ),
                )
            )

    for addend in statement.find_all(exp.Add):
        addend_cols = {c.name for c in addend.find_all(exp.Column)}
        for group in rules.non_additive_count_groups:
            if set(group) <= addend_cols:
                violations.append(
                    Violation(
                        code="sql_non_additive_sum",
                        message=(
                            f"'{addend.sql()}' adds {' and '.join(group)}, which overlap -- "
                            "report each count separately instead"
                        ),
                    )
                )

    return violations


_COVERAGE_COLUMNS = {"salesyear": "years", "salesmonth": "months"}


def _literal_ints(node: exp.Expression) -> list[int] | None:
    """Integer value(s) a literal or a tuple of literals holds, or None if it isn't one."""
    if isinstance(node, exp.Literal) and node.is_int:
        return [int(node.this)]
    if isinstance(node, exp.Tuple):
        values = [_literal_ints(e) for e in node.expressions]
        if all(v is not None for v in values):
            return [n for v in values for n in (v or [])]
    return None


def _check_coverage(statement: exp.Expression, rules: SqlRules) -> list[Violation]:
    """Layer 3: a filter entirely outside the data's actual year/month range would silently
    return 0 rows -- catch that before execution rather than let an empty result pass as
    a real answer (docs/specs/text_to_sql_safety.md's "data coverage" trap)."""
    violations: list[Violation] = []
    for comparison in statement.find_all(exp.EQ, exp.In, exp.Between):
        column = next(
            (c for c in comparison.find_all(exp.Column) if c.name.lower() in _COVERAGE_COLUMNS),
            None,
        )
        if column is None:
            continue
        allowed = set(rules.data_coverage[_COVERAGE_COLUMNS[column.name.lower()]])

        if isinstance(comparison, exp.EQ):
            other = comparison.right if comparison.left is column else comparison.left
            queried = _literal_ints(cast("exp.Expression", other))
        elif isinstance(comparison, exp.In):
            queried = _literal_ints(exp.Tuple(expressions=comparison.args.get("expressions", [])))
        else:  # exp.Between
            lo, hi = _literal_ints(comparison.args["low"]), _literal_ints(comparison.args["high"])
            queried = list(range(lo[0], hi[0] + 1)) if lo and hi and lo[0] <= hi[0] else None

        if queried and not (set(queried) & allowed):
            violations.append(
                Violation(
                    code="sql_coverage_out_of_range",
                    message=(
                        f"'{comparison.sql()}' filters {column.name} to {sorted(set(queried))}, "
                        f"entirely outside the data's coverage ({sorted(allowed)}) -- this would "
                        "return 0 rows, not a real answer; say the data doesn't cover this instead"
                    ),
                )
            )
    return violations


def _apply_limit(statement: exp.Expression) -> tuple[exp.Expression, bool]:
    """Cap (or inject) LIMIT at MAX_LIMIT. Returns the possibly-modified statement and whether
    the cap actually changed anything, so the caller can tell the person their result was capped."""
    if not isinstance(statement, exp.Select):
        return statement, False
    existing = statement.args.get("limit")
    if existing is None:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
        return statement, True
    try:
        n = int(existing.expression.sql())
    except (ValueError, AttributeError):
        return statement, False
    if n > MAX_LIMIT:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
        return statement, True
    return statement, False


def validate(
    sql: str,
    role: Role,
    policy: DisclosurePolicy,
    rules: SqlRules | None = None,
) -> ValidationResult:
    """Run every layer against `sql`. Never executes the query -- this is a static check."""
    rules = rules or load_rules()

    try:
        statements = sqlglot.parse(sql, read=DIALECT)
    except ParseError as exc:
        return ValidationResult(
            ok=False, sql=sql, violations=[Violation(code="sql_parse_error", message=str(exc))]
        )

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return ValidationResult(
            ok=False,
            sql=sql,
            violations=[
                Violation(
                    code="sql_multi_statement",
                    message=f"expected exactly one statement, got {len(statements)}",
                )
            ],
        )

    assert statements[0] is not None  # noqa: S101 -- sqlglot.parse never returns None for valid SQL
    statement = cast("exp.Expression", statements[0])
    if isinstance(statement, _BLOCKED_STATEMENT_TYPES):
        return ValidationResult(
            ok=False,
            sql=sql,
            violations=[
                Violation(
                    code="sql_statement_not_allowed",
                    message=f"'{type(statement).__name__}' statements are not allowed",
                )
            ],
        )

    violations = _check_structure(statement, policy, role)
    if violations:
        return ValidationResult(ok=False, sql=sql, violations=violations)

    violations = _check_cost_limit(statement)
    if violations:
        return ValidationResult(ok=False, sql=sql, violations=violations)

    violations = _check_semantics(statement, rules)
    if violations:
        return ValidationResult(ok=False, sql=sql, violations=violations)

    violations = _check_coverage(statement, rules)
    if violations:
        return ValidationResult(ok=False, sql=sql, violations=violations)

    capped_statement, truncated = _apply_limit(statement)
    return ValidationResult(ok=True, sql=capped_statement.sql(dialect=DIALECT), truncated=truncated)
