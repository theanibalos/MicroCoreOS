import pytest
from tools.sqlite.sqlite_tool import SqliteTool

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    # No domains/ in tmp_path, so setup()'s own migration pass is a no-op;
    # each test builds its own tables directly via db.execute().
    monkeypatch.chdir(tmp_path)
    tool = SqliteTool()
    await tool.setup()
    yield tool
    await tool.shutdown()


async def test_describe_schema_normalizes_column_types(db):
    """
    Every declared type collapses to the closed seven-value vocabulary:
    text/int/float/bool/timestamp/json/blob.
    """
    await db.execute("""
        CREATE TABLE things (
            a VARCHAR(200),
            b INTEGER,
            c TIMESTAMP,
            d BOOLEAN,
            e JSON,
            f BLOB,
            g REAL
        )
    """)

    schema = await db.describe_schema()
    columns_by_name = {c["name"]: c["type"] for c in schema["things"]["columns"]}

    assert columns_by_name == {
        "a": "text",
        "b": "int",
        "c": "timestamp",
        "d": "bool",
        "e": "json",
        "f": "blob",
        "g": "float",
    }


async def test_describe_schema_preserves_physical_column_order(db):
    await db.execute("CREATE TABLE ordered (z INTEGER, a INTEGER, m INTEGER)")
    schema = await db.describe_schema()
    names = [c["name"] for c in schema["ordered"]["columns"]]
    assert names == ["z", "a", "m"]


async def test_describe_schema_nullable_and_default(db):
    await db.execute("""
        CREATE TABLE cfg (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active BOOLEAN DEFAULT 1
        )
    """)

    schema = await db.describe_schema()
    columns_by_name = {c["name"]: c for c in schema["cfg"]["columns"]}

    assert columns_by_name["name"]["nullable"] is False
    assert columns_by_name["name"]["default"] is None

    assert columns_by_name["created_at"]["nullable"] is True
    assert columns_by_name["created_at"]["default"] == "CURRENT_TIMESTAMP"

    assert columns_by_name["active"]["nullable"] is True
    assert columns_by_name["active"]["default"] == "1"


async def test_describe_schema_primary_key(db):
    await db.execute("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            label TEXT
        )
    """)

    schema = await db.describe_schema()
    columns_by_name = {c["name"]: c for c in schema["items"]["columns"]}

    assert columns_by_name["id"]["primary_key"] is True
    assert columns_by_name["label"]["primary_key"] is False


async def test_describe_schema_unique_single_and_composite(db):
    """
    A single-column UNIQUE is [["email"]]; a composite UNIQUE(domain, filename)
    is [["domain", "filename"]]. The PRIMARY KEY is never repeated here.
    Ordering is alphabetical by each sublist's first column.
    """
    await db.execute("""
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE,
            domain TEXT,
            filename TEXT,
            UNIQUE(domain, filename)
        )
    """)

    schema = await db.describe_schema()
    assert schema["accounts"]["unique"] == [["domain", "filename"], ["email"]]


async def test_describe_schema_foreign_keys(db):
    await db.execute("CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT)")
    await db.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            role_id INTEGER,
            FOREIGN KEY(role_id) REFERENCES roles(id)
        )
    """)

    schema = await db.describe_schema()
    assert schema["users"]["foreign_keys"] == [
        {"column": "role_id", "references_table": "roles", "references_column": "id"},
    ]


async def test_describe_schema_marks_internal_tables_by_underscore_prefix(db):
    """
    `internal` is a pure naming convention: any table starting with "_" is
    internal, no hardcoded list of names.
    """
    await db.execute("CREATE TABLE _secrets (id INTEGER PRIMARY KEY)")
    await db.execute("CREATE TABLE public_stuff (id INTEGER PRIMARY KEY)")

    schema = await db.describe_schema()

    assert schema["_secrets"]["internal"] is True
    assert schema["public_stuff"]["internal"] is False
    # _migrations_history is created by setup() itself and follows the same rule.
    assert schema["_migrations_history"]["internal"] is True


async def test_describe_schema_excludes_engine_owned_tables(db):
    """
    sqlite_sequence (created implicitly by AUTOINCREMENT) is owned by the
    engine, not the system: it must be excluded entirely, not merely marked
    internal.
    """
    await db.execute("CREATE TABLE seq_demo (id INTEGER PRIMARY KEY AUTOINCREMENT)")

    schema = await db.describe_schema()

    assert "sqlite_sequence" not in schema
    assert "seq_demo" in schema


async def test_describe_schema_tables_in_alphabetical_order(db):
    await db.execute("CREATE TABLE zeta (id INTEGER PRIMARY KEY)")
    await db.execute("CREATE TABLE alpha (id INTEGER PRIMARY KEY)")
    await db.execute("CREATE TABLE mid (id INTEGER PRIMARY KEY)")

    schema = await db.describe_schema()

    assert list(schema.keys()) == sorted(schema.keys())
