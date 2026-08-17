"""Resolves the ACTIVE `db` tool — the one currently living in `tools/`.

WHY THIS EXISTS
───────────────
docs/ELASTIC_DEPLOYMENT.md (Stage 1) promises that after a db swap "the same
suite exercises the new engine with zero extra configuration", because the swap
MOVES DIRECTORIES:

    mv tools/sqlite extras/available_tools/sqlite
    mv extras/available_tools/postgresql tools/postgresql

A test that hardcodes `from tools.sqlite.sqlite_tool import SqliteTool` does not
keep that promise: after the swap the import raises ModuleNotFoundError and the
suite dies at collection — it never gets to prove anything about the new engine.
Tests that use this helper follow the active tool wherever it lives, so a failing
test after a swap means "this plugin's SQL broke on the new engine", which is the
signal the deployment guide relies on.

WHAT IT DOES *NOT* DO
─────────────────────
It does not pick an engine. tests/tools/db/test_db_parity.py imports BOTH classes on
purpose — its job is comparing engines side by side, which needs both at once.
This helper is for the plugin suites, whose job is proving a feature works on
whichever engine is installed.

USAGE
─────
    from tests.helpers.active_db import active_db

    MIGRATIONS_DIR = Path(...) / "domains" / "users" / "migrations"

    @pytest.fixture
    async def db(monkeypatch):
        async with active_db(monkeypatch, MIGRATIONS_DIR) as tool:
            yield tool
"""

import importlib.util
import inspect
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from microcoreos import BaseTool, ToolUnavailableError

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"

# Test configuration for EVERY engine we ship, applied all at once: each tool
# reads only its own variables, so this helper never has to know which engine is
# active — that is the whole point. A new db tool adds its variables here.
_TEST_ENV = {
    # SQLite
    "SQLITE_DB_PATH": ":memory:",
    # PostgreSQL
    "PG_HOST": "localhost",
    "PG_PORT": "5432",
    "PG_USER": "postgres",
    "PG_PASSWORD": "postgres",
    "PG_DATABASE": "microcoreos_test",
    # Tests apply the migrations they need explicitly (below), so boot-time
    # auto-migration would only add unrelated domains' tables.
    "DB_AUTO_MIGRATE": "false",
}

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?", re.IGNORECASE
)

_cached_class: type | None = None


def load_active_db_tool_class() -> type:
    """The class of the tool in `tools/` whose name is "db".

    Mirrors the kernel's discovery (microcoreos/kernel.py::_load_modules_from_dir),
    narrowed to `*_tool.py` files — the repo convention — so probing never
    imports optional drivers that may not be installed.
    """
    global _cached_class
    if _cached_class is not None:
        return _cached_class

    for path in sorted(_TOOLS_DIR.rglob("*_tool.py")):
        module_name = f"active_db_probe_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue  # a tool whose optional dependency is missing is not our db tool

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BaseTool) or obj is BaseTool:
                continue
            if obj.__module__ != module.__name__:
                continue
            try:
                if obj().name == "db":
                    _cached_class = obj
                    return obj
            except Exception:
                continue  # constructors are config-only by contract; anything else isn't it

    raise RuntimeError(
        f"No tool named 'db' found in {_TOOLS_DIR}. "
        "One db tool must live in tools/ (see docs/ELASTIC_DEPLOYMENT.md, Stage 1)."
    )


def _statements(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


@asynccontextmanager
async def active_db(monkeypatch, *migration_dirs: Path):
    """Boots the active db tool, applies the given migrations, and cleans up.

    Skips the test if the engine's server is unreachable (ToolUnavailableError —
    the contract every db tool's connection error implements), the same way the
    parity suite skips when PostgreSQL is down.

    Migrations run VERBATIM, exactly as on boot: if a migration is not portable
    to the active engine, these tests are supposed to fail — that is the
    behavioral gate described in docs/ELASTIC_DEPLOYMENT.md, not a bug here.
    """
    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)

    tool_cls = load_active_db_tool_class()
    tool = tool_cls()
    try:
        await tool.setup()
    except ToolUnavailableError as e:
        if "does not exist" in str(e).lower() and tool_cls.__name__ == "PostgresqlTool":
            try:
                import os
                import asyncpg
                host = os.getenv("PG_HOST", "localhost")
                port = int(os.getenv("PG_PORT", "5432"))
                user = os.getenv("PG_USER", "postgres")
                password = os.getenv("PG_PASSWORD", "postgres")
                dbname = os.getenv("PG_DATABASE", "microcoreos_test")
                conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database="postgres")
                await conn.execute(f'CREATE DATABASE "{dbname}"')
                await conn.close()
                await tool.setup()
            except Exception:
                pytest.skip(f"active db tool {tool_cls.__name__} is unreachable: {e}")
        else:
            pytest.skip(f"active db tool {tool_cls.__name__} is unreachable: {e}")

    from graphlib import TopologicalSorter

    all_migrations: dict[str, dict] = {}
    for migrations_dir in migration_dirs:
        domain = migrations_dir.parent.name
        for migration in sorted(migrations_dir.glob("*.sql")):
            key = f"{domain}/{migration.name}"
            depends = []
            with open(migration, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith("-- depends:"):
                        dep = line.split(":", 1)[1].strip()
                        if not dep.endswith(".sql"):
                            dep += ".sql"
                        depends.append(dep)
                    elif line.startswith("--"):
                        continue
                    else:
                        break
            all_migrations[key] = {
                "path": migration,
                "depends": depends,
            }

    graph = {k: set(v["depends"]) for k, v in all_migrations.items()}
    try:
        sorter = TopologicalSorter(graph)
        ordered_keys = [k for k in sorter.static_order() if k in all_migrations]
    except Exception:
        ordered_keys = list(all_migrations.keys())

    tables: list[str] = []
    try:
        for key in ordered_keys:
            migration = all_migrations[key]["path"]
            sql = migration.read_text(encoding="utf-8")
            tables.extend(_CREATE_TABLE_RE.findall(sql))
            for statement in _statements(sql):
                await tool.execute(statement)
        yield tool
    finally:
        # SQLite :memory: dies with the connection, but an engine backed by a
        # real server keeps every table between tests — drop what we created,
        # children first (reverse creation order). On PostgreSQL, use CASCADE
        # so foreign keys left by dependent tables don't prevent dropping.
        is_pg = tool_cls.__name__ == "PostgresqlTool"
        for table in reversed(tables):
            try:
                drop_sql = f"DROP TABLE IF EXISTS {table} CASCADE" if is_pg else f"DROP TABLE IF EXISTS {table}"
                await tool.execute(drop_sql)
            except Exception:
                pass
        await tool.shutdown()

