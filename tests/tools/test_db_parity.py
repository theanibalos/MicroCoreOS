"""
Database contract parity suite (Issue 22 pattern).

Every tool that acts as "db" MUST pass this battery — it is the
executable version of the contract defined in
extras/available_tools/postgresql/postgresql_tool.py (the gold standard).

The suite runs parametrized over all known implementations:

    - sqlite:      SqliteTool, always runs (in-memory, no infra needed)
    - postgresql:  PostgresqlTool, skips if no server is reachable
                   (docker compose -f dev_infra/docker-compose.yml up -d postgres)

DDL uses a common subset: INTEGER PRIMARY KEY, TEXT NOT NULL, and explicit
IDs — no SERIAL — so the same SQL runs on both engines without adaptation.
"""

import pytest

from tools.sqlite.sqlite_tool import SqliteTool
from extras.available_tools.postgresql.postgresql_tool import (
    PostgresqlTool,
    DatabaseConnectionError as PGConnectionError,
)

pytestmark = pytest.mark.anyio

_TABLE_DDL = "CREATE TABLE _parity (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["sqlite", "postgresql"])
async def db(request, monkeypatch):
    if request.param == "sqlite":
        monkeypatch.setenv("SQLITE_DB_PATH", ":memory:")
        tool = SqliteTool()
        await tool.setup()
        yield tool
        await tool.shutdown()
        return

    monkeypatch.setenv("PG_HOST", "localhost")
    monkeypatch.setenv("PG_PORT", "5432")
    monkeypatch.setenv("PG_USER", "postgres")
    monkeypatch.setenv("PG_PASSWORD", "postgres")
    monkeypatch.setenv("PG_DATABASE", "microcoreos")
    monkeypatch.setenv("DB_AUTO_MIGRATE", "false")
    tool = PostgresqlTool()
    try:
        await tool.setup()
    except PGConnectionError:
        pytest.skip(
            "PostgreSQL not available — "
            "docker compose -f dev_infra/docker-compose.yml up -d postgres"
        )
    yield tool
    await tool.execute("DROP TABLE IF EXISTS _parity")
    await tool.shutdown()


@pytest.fixture
async def table(db):
    await db.execute(_TABLE_DDL)
    yield db
    await db.execute("DROP TABLE IF EXISTS _parity")


# ─── Basic reads / writes ─────────────────────────────────────────────────────

async def test_execute_insert_returns_affected_rows(table):
    affected = await table.execute(
        "INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"]
    )
    assert affected == 1


async def test_execute_insert_with_returning(table):
    row_id = await table.execute(
        "INSERT INTO _parity (id, name) VALUES ($1, $2) RETURNING id", [42, "Ana"]
    )
    assert row_id == 42


async def test_query_returns_list_of_dicts(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    rows = await table.query("SELECT id, name FROM _parity")
    assert rows == [{"id": 1, "name": "Ana"}]


async def test_query_empty_table_returns_empty_list(table):
    assert await table.query("SELECT * FROM _parity") == []


async def test_query_with_params(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [2, "Bob"])
    rows = await table.query("SELECT * FROM _parity WHERE id = $1", [2])
    assert len(rows) == 1 and rows[0]["name"] == "Bob"


async def test_query_one_returns_first_matching_row(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    row = await table.query_one("SELECT * FROM _parity WHERE id = $1", [1])
    assert row is not None and row["name"] == "Ana"


async def test_query_one_missing_returns_none(table):
    assert await table.query_one("SELECT * FROM _parity WHERE id = $1", [99]) is None


async def test_update_returns_affected_rows(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    affected = await table.execute("UPDATE _parity SET name = $1 WHERE id = $2", ["Bob", 1])
    assert affected == 1


async def test_update_no_match_returns_zero(table):
    affected = await table.execute("UPDATE _parity SET name = $1 WHERE id = $2", ["X", 99])
    assert affected == 0


async def test_delete_removes_row(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    affected = await table.execute("DELETE FROM _parity WHERE id = $1", [1])
    assert affected == 1
    assert await table.query("SELECT * FROM _parity") == []


# ─── execute_many ─────────────────────────────────────────────────────────────

async def test_execute_many_inserts_all_rows(table):
    await table.execute_many(
        "INSERT INTO _parity (id, name) VALUES ($1, $2)",
        [[1, "A"], [2, "B"], [3, "C"]],
    )
    rows = await table.query("SELECT id FROM _parity ORDER BY id")
    assert [r["id"] for r in rows] == [1, 2, 3]


async def test_execute_many_empty_list_is_noop(table):
    await table.execute_many("INSERT INTO _parity (id, name) VALUES ($1, $2)", [])
    assert await table.query("SELECT * FROM _parity") == []


# ─── Transactions ─────────────────────────────────────────────────────────────

async def test_transaction_commits_on_success(table):
    async with table.transaction() as tx:
        await tx.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "TxA"])
        await tx.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [2, "TxB"])
    rows = await table.query("SELECT name FROM _parity ORDER BY id")
    assert [r["name"] for r in rows] == ["TxA", "TxB"]


async def test_transaction_rolls_back_on_exception(table):
    try:
        async with table.transaction() as tx:
            await tx.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "WillRollback"])
            raise ValueError("forced rollback")
    except ValueError:
        pass
    assert await table.query("SELECT * FROM _parity") == []


async def test_transaction_query_sees_own_writes(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    async with table.transaction() as tx:
        rows = await tx.query("SELECT name FROM _parity WHERE id = $1", [1])
        assert rows[0]["name"] == "Ana"


async def test_transaction_query_one_within_tx(table):
    await table.execute("INSERT INTO _parity (id, name) VALUES ($1, $2)", [1, "Ana"])
    async with table.transaction() as tx:
        row = await tx.query_one("SELECT name FROM _parity WHERE id = $1", [1])
        assert row is not None and row["name"] == "Ana"


async def test_transaction_execute_returning_within_tx(table):
    async with table.transaction() as tx:
        val = await tx.execute(
            "INSERT INTO _parity (id, name) VALUES ($1, $2) RETURNING id", [77, "Tx"]
        )
    assert val == 77


# ─── health_check ─────────────────────────────────────────────────────────────

async def test_health_check_returns_true(db):
    assert await db.health_check() is True
