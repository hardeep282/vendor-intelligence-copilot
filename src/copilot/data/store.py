"""DuckDB access to the licence-safe snapshot, hardened for LLM-generated SQL.

Purpose : the only way any agent reads data. Even if a malicious query got past the SQL
          validator (Day 3), the engine itself refuses to touch files, the network or its
          own configuration, and refuses every write.
Inputs  : the snapshot directory (default from settings) holding the Parquet tables.
Outputs : a read-only DuckDB connection over `snapshot.duckdb`, built from the Parquet files.

Defence layers here (layer 0 of the text-to-SQL safety design, docs/specs/text_to_sql_safety.md):
  1. Only aggregate tables exist in the database (licence guard at build time).
  2. The database file is opened read_only=True: INSERT/UPDATE/DELETE/CREATE all fail.
  3. enable_external_access=false: read_csv/read_parquet/glob/ATTACH/COPY/INSTALL all fail.
  4. lock_configuration=true: a query cannot switch 3 back on.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from copilot.settings import get_settings

DB_NAME = "snapshot.duckdb"


def snapshot_tables(snapshot_dir: Path | None = None) -> list[str]:
    """Names of the tables present in the snapshot directory (one per Parquet file)."""
    d = snapshot_dir or get_settings().snapshot_dir
    return sorted(p.stem for p in d.glob("*.parquet"))


def build_database(snapshot_dir: Path | None = None) -> Path:
    """(Re)create snapshot.duckdb from the Parquet files. Run after build_snapshot.py."""
    d = snapshot_dir or get_settings().snapshot_dir
    db_path = d / DB_NAME
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for name in snapshot_tables(d):
            src = (d / f"{name}.parquet").as_posix()
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{src}')")  # noqa: S608
    finally:
        con.close()
    return db_path


def connect(snapshot_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open the snapshot read-only, with file/network access off and configuration locked."""
    d = snapshot_dir or get_settings().snapshot_dir
    db_path = d / DB_NAME
    newest_parquet = max((p.stat().st_mtime for p in d.glob("*.parquet")), default=0.0)
    if not db_path.exists() or db_path.stat().st_mtime < newest_parquet:
        build_database(d)
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con
