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
    monkeypatch.setenv("PG_DATABASE", "microcoreos_test")
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


# ─── describe_schema: CROSS-ENGINE equality ───────────────────────────────────
#
# The rest of this suite is parametrized: it proves each engine satisfies the
# contract on its own. describe_schema() needs the stronger check — the SAME
# migration must yield the SAME description on BOTH engines, or the manifest
# would change meaning when the db tool is swapped, and the manifest is what
# every agent reads. So this section builds both tools at once and compares
# with ==.
#
# DDL restricted to the portable subset (no BLOB/BYTEA, no SERIAL): per-engine
# type coverage lives in each tool's own describe_schema test file.

_SCHEMA_DDL = """
CREATE TABLE _parity_schema (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    age         INTEGER,
    score       DOUBLE PRECISION NOT NULL,
    active      BOOLEAN NOT NULL,
    created_at  TIMESTAMP
)
"""


@pytest.fixture
async def both_engines(monkeypatch):
    """Both db implementations, live at the same time, on identical DDL."""
    monkeypatch.setenv("SQLITE_DB_PATH", ":memory:")
    sqlite_tool = SqliteTool()
    await sqlite_tool.setup()

    monkeypatch.setenv("PG_HOST", "localhost")
    monkeypatch.setenv("PG_PORT", "5432")
    monkeypatch.setenv("PG_USER", "postgres")
    monkeypatch.setenv("PG_PASSWORD", "postgres")
    monkeypatch.setenv("PG_DATABASE", "microcoreos_test")
    monkeypatch.setenv("DB_AUTO_MIGRATE", "false")
    pg_tool = PostgresqlTool()
    try:
        await pg_tool.setup()
    except PGConnectionError:
        await sqlite_tool.shutdown()
        pytest.skip(
            "PostgreSQL not available — "
            "docker compose -f dev_infra/docker-compose.yml up -d postgres"
        )

    await pg_tool.execute("DROP TABLE IF EXISTS _parity_schema")
    for tool in (sqlite_tool, pg_tool):
        await tool.execute(_SCHEMA_DDL)

    yield sqlite_tool, pg_tool

    await pg_tool.execute("DROP TABLE IF EXISTS _parity_schema")
    await sqlite_tool.shutdown()
    await pg_tool.shutdown()


async def test_describe_schema_is_identical_across_engines(both_engines):
    """The whole point: swapping the db tool must not change the manifest."""
    sqlite_tool, pg_tool = both_engines

    sqlite_desc = (await sqlite_tool.describe_schema())["_parity_schema"]
    pg_desc = (await pg_tool.describe_schema())["_parity_schema"]

    assert sqlite_desc == pg_desc


async def test_describe_schema_marks_underscore_tables_internal(both_engines):
    sqlite_tool, pg_tool = both_engines
    for tool in (sqlite_tool, pg_tool):
        schema = await tool.describe_schema()
        assert schema["_parity_schema"]["internal"] is True


async def test_describe_schema_excludes_engine_owned_tables(both_engines):
    """sqlite_sequence / sqlite_stat* and non-public Postgres tables never appear."""
    sqlite_tool, pg_tool = both_engines
    for tool in (sqlite_tool, pg_tool):
        schema = await tool.describe_schema()
        assert not any(name.startswith("sqlite_") for name in schema)
        assert not any(name.startswith("pg_") for name in schema)


# ─── ERROR CONTRACT ───────────────────────────────────────────────────────────
#
# describe_schema parity proves the swap keeps the SHAPE of the data. This
# section proves it keeps the BEHAVIOR ON FAILURE, which is the other half a
# plugin depends on: a plugin branches on `kind` to turn a constraint violation
# into a business answer ("Email already in use"), so if two engines classify
# the same violation differently, the swap changes observable behavior with
# every test still green.
#
# Engines report violations in completely different ways (SQLite: message text,
# PostgreSQL: SQLSTATE) — `kind` is the contract that makes them equivalent.

_ERROR_DDL = """
CREATE TABLE _parity_err (
    id     INTEGER PRIMARY KEY,
    email  TEXT NOT NULL UNIQUE,
    age    INTEGER CHECK (age >= 0)
)
"""

_ERROR_CHILD_DDL = """
CREATE TABLE _parity_err_child (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER NOT NULL REFERENCES _parity_err(id)
)
"""


async def _create_error_tables(tool):
    await tool.execute("DROP TABLE IF EXISTS _parity_err_child")
    await tool.execute("DROP TABLE IF EXISTS _parity_err")
    await tool.execute(_ERROR_DDL)
    await tool.execute(_ERROR_CHILD_DDL)
    await tool.execute("INSERT INTO _parity_err (id, email, age) VALUES ($1, $2, $3)", [1, "a@b.c", 30])


async def _drop_error_tables(tool):
    await tool.execute("DROP TABLE IF EXISTS _parity_err_child")
    await tool.execute("DROP TABLE IF EXISTS _parity_err")


async def _violate(tool, what: str):
    """Triggers one violation and returns the raised exception."""
    statements = {
        # id 1 already exists with this email
        "unique": ("INSERT INTO _parity_err (id, email) VALUES ($1, $2)", [2, "a@b.c"]),
        "not_null": ("INSERT INTO _parity_err (id, email) VALUES ($1, $2)", [3, None]),
        "check": ("INSERT INTO _parity_err (id, email, age) VALUES ($1, $2, $3)", [4, "d@e.f", -1]),
        "foreign_key": ("INSERT INTO _parity_err_child (id, parent_id) VALUES ($1, $2)", [1, 999]),
    }
    sql, params = statements[what]
    with pytest.raises(Exception) as excinfo:
        await tool.execute(sql, params)
    return excinfo.value


@pytest.fixture
async def error_table(db):
    await _create_error_tables(db)
    yield db
    await _drop_error_tables(db)


@pytest.mark.parametrize(
    "violation, expected_kind",
    [
        ("unique", "unique_violation"),
        ("not_null", "not_null_violation"),
        ("check", "check_violation"),
        ("foreign_key", "foreign_key_violation"),
    ],
)
async def test_violation_is_classified(error_table, violation, expected_kind):
    """Each engine, on its own, must classify every integrity violation."""
    error = await _violate(error_table, violation)
    assert getattr(error, "kind", None) == expected_kind


async def test_unclassified_failure_is_unknown_not_a_guess(error_table):
    """A non-integrity failure must NOT be forced into a business kind."""
    with pytest.raises(Exception) as excinfo:
        await error_table.query("SELECT * FROM _table_that_does_not_exist")
    assert getattr(excinfo.value, "kind", None) == "unknown"


async def test_unique_violation_reports_table_and_columns(error_table):
    error = await _violate(error_table, "unique")
    assert error.table == "_parity_err"
    assert error.columns == ("email",)


async def test_not_null_violation_reports_table_and_columns(error_table):
    error = await _violate(error_table, "not_null")
    assert error.table == "_parity_err"
    assert error.columns == ("email",)


@pytest.mark.parametrize("violation", ["foreign_key", "check"])
async def test_untargetable_violations_carry_kind_only(error_table, violation):
    """SQLite reports no target for these, so NO engine may report one —
    a field that exists on PostgreSQL and vanishes after the swap is worse
    than one that is always empty (see the db tools' DatabaseError)."""
    error = await _violate(error_table, violation)
    assert error.table is None
    assert error.columns == ()


async def test_violation_inside_transaction_is_classified(error_table):
    """tx.execute() must classify exactly like db.execute() — the plugin's
    except block is the same one either way."""
    with pytest.raises(Exception) as excinfo:
        async with error_table.transaction() as tx:
            await tx.execute("INSERT INTO _parity_err (id, email) VALUES ($1, $2)", [2, "a@b.c"])
    assert getattr(excinfo.value, "kind", None) == "unique_violation"


# ─── Error contract: CROSS-ENGINE equality ────────────────────────────────────
#
# Same reasoning as describe_schema above: proving each engine classifies on
# its own is not enough — the two must produce the SAME classification for the
# SAME violation, or a plugin's `if kind == "unique_violation"` starts meaning
# something different after the swap.


@pytest.fixture
async def both_engines_errors(both_engines):
    sqlite_tool, pg_tool = both_engines
    for tool in (sqlite_tool, pg_tool):
        await _create_error_tables(tool)
    yield sqlite_tool, pg_tool
    for tool in (sqlite_tool, pg_tool):
        await _drop_error_tables(tool)


@pytest.mark.parametrize("violation", ["unique", "not_null", "check", "foreign_key"])
async def test_violation_classification_is_identical_across_engines(both_engines_errors, violation):
    """The whole point: swapping the db tool must not change what a plugin sees."""
    sqlite_tool, pg_tool = both_engines_errors

    sqlite_error = await _violate(sqlite_tool, violation)
    pg_error = await _violate(pg_tool, violation)

    def contract(error):
        return (error.kind, error.table, error.columns)

    assert contract(sqlite_error) == contract(pg_error)
