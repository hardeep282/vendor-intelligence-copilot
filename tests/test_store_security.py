"""Layer-0 SQL safety: the database engine itself refuses dangerous statements.

These run against the real snapshot (skipped when it has not been built). Each attack is one
that an LLM could be tricked into writing; the engine must refuse it even if the SQL validator
(Day 3) were bypassed.
"""

import duckdb
import pytest

from copilot.data.store import DB_NAME, connect
from copilot.settings import get_settings

# Checks the real database file (DB_NAME), not MANIFEST.json -- see the matching fix and
# comment in tests/test_golden.py. The parametrized `test_engine_refuses` attacks happened to
# keep passing even with this check broken (most of them fail for a security reason regardless
# of whether real tables exist, and `pytest.raises(duckdb.Error)` accepts any duckdb error,
# CatalogException included); only `test_aggregate_reads_still_work`'s exact-count assertion
# actually surfaced the bug.
pytestmark = pytest.mark.skipif(
    not (get_settings().snapshot_dir / DB_NAME).exists(), reason="snapshot not built"
)

ATTACKS = {
    "read a local file": "SELECT * FROM read_csv('/etc/passwd')",
    "read the .env file": "SELECT * FROM read_text('.env')",
    "list the file system": "SELECT * FROM glob('/*')",
    "attach another database": "ATTACH 'stolen.db' AS s",
    "export data to a file": "COPY vendor_tiering TO 'out.csv'",
    "install a network extension": "INSTALL httpfs",
    "re-enable file access": "SET enable_external_access = true",
    "write to a table": "INSERT INTO vendor_tiering SELECT * FROM vendor_tiering LIMIT 1",
    "drop a table": "DROP TABLE vendor_tiering",
    "create a table": "CREATE TABLE x AS SELECT 1",
}


@pytest.mark.parametrize("attack", list(ATTACKS), ids=list(ATTACKS))
def test_engine_refuses(attack: str) -> None:
    con = connect()
    with pytest.raises(duckdb.Error):
        con.execute(ATTACKS[attack])


def test_aggregate_reads_still_work() -> None:
    row = connect().execute("SELECT count(*) FROM vendor_tiering").fetchone()
    assert row is not None and row[0] == 126
