"""DuckDB access to the licence-safe snapshot.

Purpose : one function that returns a DuckDB connection with a view per snapshot table.
Inputs  : the snapshot directory (default from settings).
Outputs : a read-only-in-spirit in-memory connection; every table is a view over Parquet.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from copilot.settings import get_settings


def snapshot_tables(snapshot_dir: Path | None = None) -> list[str]:
    """Names of the tables present in the snapshot directory."""
    d = snapshot_dir or get_settings().snapshot_dir
    return sorted(p.stem for p in d.glob("*.parquet"))


def connect(snapshot_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with one view per Parquet file."""
    d = snapshot_dir or get_settings().snapshot_dir
    con = duckdb.connect(":memory:")
    for name in snapshot_tables(d):
        path = (d / f"{name}.parquet").as_posix()
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path}')")  # noqa: S608
    return con
