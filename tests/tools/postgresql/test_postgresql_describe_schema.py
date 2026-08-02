"""
Tests for PostgresqlTool.describe_schema() — the PostgreSQL side of the
frozen contract in
/tmp/claude-1000/-home-anibalos-Documents-Original-MicroCoreOS/4afec8be-9a68-4ed3-86fc-04c347d2cfbf/scratchpad/describe_schema_contract.md

Mirrors the SQLite-side coverage: normalized types, nullable, default,
primary_key, single/composite unique, foreign_keys, and the "_"-prefix
convention for internal tables. Exact byte-for-byte agreement between
engines is covered separately by tests/tools/test_db_parity.py — this
file only exercises the PostgreSQL implementation on its own.
"""

import pytest

from extras.available_tools.postgresql.postgresql_tool import (
    PostgresqlTool,
    DatabaseConnectionError,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def pg_env(monkeypatch):
    monkeypatch.setenv("PG_HOST", "localhost")
    monkeypatch.setenv("PG_PORT", "5432")
    monkeypatch.setenv("PG_USER", "postgres")
    monkeypatch.setenv("PG_PASSWORD", "postgres")
    monkeypatch.setenv("PG_DATABASE", "microcoreos")
    monkeypatch.setenv("DB_AUTO_MIGRATE", "false")


@pytest.fixture
async def db():
    tool = PostgresqlTool()
    try:
        await tool.setup()
    except DatabaseConnectionError:
        pytest.skip(
            "PostgreSQL not available — "
            "docker compose -f dev_infra/docker-compose.yml up -d postgres"
        )
    yield tool
    await tool.shutdown()


# ─── Type vocabulary ───────────────────────────────────────────────────────

async def test_normalizes_common_types_to_closed_vocabulary(db):
    table = "describe_types_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                a VARCHAR(50),
                b INTEGER,
                c TIMESTAMPTZ,
                d BOOLEAN,
                e JSONB,
                f BYTEA,
                g NUMERIC(10, 2)
            )
        """)
        schema = await db.describe_schema()
        cols = {c["name"]: c["type"] for c in schema[table]["columns"]}
        assert cols == {
            "a": "text",
            "b": "int",
            "c": "timestamp",
            "d": "bool",
            "e": "json",
            "f": "blob",
            "g": "float",
        }
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


async def test_type_vocabulary_has_only_seven_closed_values(db):
    table = "describe_types_closed_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                a TEXT,
                b BIGINT,
                c REAL,
                d DOUBLE PRECISION,
                e DATE,
                f TIME,
                g CHAR(1)
            )
        """)
        schema = await db.describe_schema()
        types = {c["type"] for c in schema[table]["columns"]}
        assert types <= {"text", "int", "float", "bool", "timestamp", "json", "blob"}
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


# ─── Columns: order, nullable, default ─────────────────────────────────────

async def test_columns_preserve_physical_order(db):
    table = "describe_order_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                z INTEGER,
                a INTEGER,
                m INTEGER
            )
        """)
        schema = await db.describe_schema()
        names = [c["name"] for c in schema[table]["columns"]]
        assert names == ["z", "a", "m"]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


async def test_nullable_and_default(db):
    table = "describe_nullable_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                required_field TEXT NOT NULL,
                optional_field TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        schema = await db.describe_schema()
        cols = {c["name"]: c for c in schema[table]["columns"]}

        assert cols["required_field"]["nullable"] is False
        assert cols["required_field"]["default"] is None

        assert cols["optional_field"]["nullable"] is True
        assert cols["optional_field"]["default"] is None

        assert cols["created_at"]["nullable"] is True
        assert cols["created_at"]["default"] is not None
        assert "CURRENT_TIMESTAMP" in cols["created_at"]["default"]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


# ─── Primary key ────────────────────────────────────────────────────────────

async def test_primary_key_marked_on_column_not_repeated_in_unique(db):
    table = "describe_pk_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        schema = await db.describe_schema()
        cols = {c["name"]: c for c in schema[table]["columns"]}
        assert cols["id"]["primary_key"] is True
        assert cols["name"]["primary_key"] is False
        assert schema[table]["unique"] == []
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


# ─── Unique constraints ─────────────────────────────────────────────────────

async def test_single_column_unique(db):
    table = "describe_unique_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE
            )
        """)
        schema = await db.describe_schema()
        assert schema[table]["unique"] == [["email"]]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


async def test_composite_unique(db):
    table = "describe_composite_unique_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                domain TEXT,
                filename TEXT,
                UNIQUE (domain, filename)
            )
        """)
        schema = await db.describe_schema()
        assert schema[table]["unique"] == [["domain", "filename"]]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


async def test_multiple_unique_constraints_sorted_alphabetically(db):
    table = "describe_multi_unique_tbl"
    try:
        await db.execute(f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                zeta TEXT UNIQUE,
                alpha TEXT UNIQUE
            )
        """)
        schema = await db.describe_schema()
        assert schema[table]["unique"] == [["alpha"], ["zeta"]]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


# ─── Foreign keys ───────────────────────────────────────────────────────────

async def test_foreign_keys(db):
    parent = "describe_fk_parent_tbl"
    child = "describe_fk_child_tbl"
    try:
        await db.execute(f"CREATE TABLE {parent} (id INTEGER PRIMARY KEY)")
        await db.execute(f"""
            CREATE TABLE {child} (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER REFERENCES {parent}(id)
            )
        """)
        schema = await db.describe_schema()
        assert schema[child]["foreign_keys"] == [
            {
                "column": "parent_id",
                "references_table": parent,
                "references_column": "id",
            }
        ]
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {child}")
        await db.execute(f"DROP TABLE IF EXISTS {parent}")


# ─── Internal tables ────────────────────────────────────────────────────────

async def test_table_with_leading_underscore_is_internal(db):
    table = "_describe_internal_tbl"
    try:
        await db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        schema = await db.describe_schema()
        assert schema[table]["internal"] is True
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


async def test_table_without_leading_underscore_is_not_internal(db):
    table = "describe_not_internal_tbl"
    try:
        await db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        schema = await db.describe_schema()
        assert schema[table]["internal"] is False
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {table}")


# ─── Top-level shape ────────────────────────────────────────────────────────

async def test_tables_sorted_alphabetically(db):
    t1 = "describe_zzz_tbl"
    t2 = "describe_aaa_tbl"
    try:
        await db.execute(f"CREATE TABLE {t1} (id INTEGER PRIMARY KEY)")
        await db.execute(f"CREATE TABLE {t2} (id INTEGER PRIMARY KEY)")
        schema = await db.describe_schema()
        names = [name for name in schema if name in (t1, t2)]
        assert names == sorted(names)
    finally:
        await db.execute(f"DROP TABLE IF EXISTS {t1}")
        await db.execute(f"DROP TABLE IF EXISTS {t2}")
