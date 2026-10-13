"""Licence guard for the deployable snapshot.

Purpose : make "no raw licensed rows leave the machine" a tested rule, not a habit.
Inputs  : a table name and a DataFrame (or the list of its columns and row count).
Outputs : raises LicenceViolation when a table looks like SKU-level or row-level data.
"""

from __future__ import annotations

from collections.abc import Iterable

# Columns that identify a SKU or carry SKU-level prices. Any of these means row-level data.
SKU_LEVEL_COLUMNS: frozenset[str] = frozenset(
    {"Description", "Brand", "Size", "PurchasePrice", "ActualPrice", "Volume", "StoreCount"}
)

# A vendor-by-month table is 126 x 12 = 1,512 rows. Anything bigger is suspect.
MAX_ROWS_PER_TABLE = 2000


class LicenceViolation(ValueError):
    """Raised when a table would expose licensed, row-level data."""


def check_table(name: str, columns: Iterable[str], n_rows: int) -> None:
    """Raise LicenceViolation if the table is not aggregate-only."""
    bad = sorted(SKU_LEVEL_COLUMNS.intersection(columns))
    if bad:
        raise LicenceViolation(f"{name}: SKU-level columns present: {bad}")
    if n_rows > MAX_ROWS_PER_TABLE:
        raise LicenceViolation(f"{name}: {n_rows} rows exceeds the {MAX_ROWS_PER_TABLE} row cap")
