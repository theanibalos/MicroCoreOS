import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from tools.sqlite.sqlite_tool import SqliteTool, DatabaseError, DatabaseConnectionError
from extras.available_tools.postgresql.postgresql_tool import (
    PostgresqlTool,
)
from tools.event_bus.event_bus_tool import EventBusTool
from tools.event_bus.redis_streams_driver import RedisStreamsDriver, EventBusConnectionError
from extras.available_tools.redis_state.redis_state_tool import (
    RedisStateTool,
    StateConnectionError,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ─────────────────────────────────────────────────────────────────────────────
# 1. SqliteTool Lifecycle Cleanup
# ─────────────────────────────────────────────────────────────────────────────

async def test_sqlite_setup_failure_during_migration_closes_connection(tmp_path, monkeypatch):
    """
    If a migration fails during SqliteTool.setup(), the open DB connection
    must be closed before propagating DatabaseError.
    """
    db_file = tmp_path / "fail_migration.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    monkeypatch.chdir(tmp_path)

    domains_dir = tmp_path / "domains" / "broken" / "migrations"
    domains_dir.mkdir(parents=True)
    (domains_dir / "001_bad.sql").write_text(
        "CREATE TABLE test (id int);\nINVALID SQL SYNTAX HERE;",
        encoding="utf-8",
    )

    tool = SqliteTool()
    with pytest.raises(DatabaseError) as exc_info:
        await tool.setup()

    assert "Migration failed" in str(exc_info.value)
    # Connection must be closed and internal reference reset
    assert tool._db is None

    # Idempotent shutdown: calling shutdown on the already-cleaned tool must be safe
    await tool.shutdown()
    assert tool._db is None


async def test_sqlite_setup_failure_during_connection_cleans_up(tmp_path, monkeypatch):
    """
    If PRAGMA or initial setup fails after opening the connection,
    the connection is closed and DatabaseConnectionError is raised.
    """
    tool = SqliteTool()
    monkeypatch.setattr(
        "aiosqlite.connect",
        AsyncMock(side_effect=Exception("Disk I/O error")),
    )

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await tool.setup()

    assert "Disk I/O error" in str(exc_info.value)
    assert tool._db is None


async def test_sqlite_setup_cancellation_cleans_up(tmp_path, monkeypatch):
    """
    If SqliteTool.setup() is cancelled via asyncio.CancelledError,
    resources are closed and CancelledError is re-raised.
    """
    db_file = tmp_path / "cancel.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    monkeypatch.chdir(tmp_path)

    tool = SqliteTool()

    async def mock_run_migrations(self_tool):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tool, "_run_migrations", lambda: mock_run_migrations(tool))

    with pytest.raises(asyncio.CancelledError):
        await tool.setup()

    assert tool._db is None


async def test_sqlite_setup_cleanup_error_preserves_original_exception(tmp_path, monkeypatch):
    """
    If cleanup itself encounters an error during failed setup teardown,
    the original setup failure is preserved and re-raised.
    """
    db_file = tmp_path / "cleanup_err.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    monkeypatch.chdir(tmp_path)

    tool = SqliteTool()

    # Make setup fail during migration
    async def failing_migrations(self_tool):
        raise DatabaseError("Original setup failure", kind="unknown")

    monkeypatch.setattr(tool, "_run_migrations", lambda: failing_migrations(tool))

    # Make shutdown raise an unexpected error during teardown
    async def failing_shutdown():
        raise RuntimeError("Cleanup failed unexpectedly")

    monkeypatch.setattr(tool, "shutdown", failing_shutdown)

    try:
        with pytest.raises(DatabaseError) as exc_info:
            await tool.setup()

        assert "Original setup failure" in str(exc_info.value)
    finally:
        # Properly close the underlying connection to join the aiosqlite thread
        # before the test's event loop closes
        if tool._db is not None:
            await tool._db.close()
            tool._db = None


async def test_sqlite_shutdown_idempotency_and_partial_init():
    """
    SqliteTool.shutdown() must tolerate partial initialization and repeated calls.
    """
    tool = SqliteTool()
    assert tool._db is None

    # Call shutdown on uninitialized tool
    await tool.shutdown()
    await tool.shutdown()
    assert tool._db is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. PostgresqlTool Lifecycle Cleanup
# ─────────────────────────────────────────────────────────────────────────────

async def test_postgresql_setup_failure_cleans_pool(monkeypatch):
    """
    If PostgresqlTool.setup() fails after creating the pool (e.g. during migrations),
    the pool must be closed before the error propagates.
    """
    tool = PostgresqlTool()
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=mock_pool))

    # Simulate failure during execute/migrations
    monkeypatch.setattr(
        tool,
        "execute",
        AsyncMock(side_effect=Exception("Migration table error")),
    )

    with pytest.raises(Exception) as exc_info:
        await tool.setup()

    assert "Migration table error" in str(exc_info.value)
    assert tool._pool is None
    mock_pool.close.assert_awaited_once()

    # Repeated shutdown is safe
    await tool.shutdown()


async def test_postgresql_setup_cancellation_cleans_pool(monkeypatch):
    """
    If PostgresqlTool.setup() is cancelled, the pool is closed and
    asyncio.CancelledError is re-raised.
    """
    tool = PostgresqlTool()
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=mock_pool))
    monkeypatch.setattr(
        tool,
        "execute",
        AsyncMock(side_effect=asyncio.CancelledError),
    )

    with pytest.raises(asyncio.CancelledError):
        await tool.setup()

    assert tool._pool is None
    mock_pool.close.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# 3. RedisStreamsDriver and EventBusTool Lifecycle Cleanup
# ─────────────────────────────────────────────────────────────────────────────

async def test_redis_streams_driver_setup_failure_closes_client(monkeypatch):
    """
    If RedisStreamsDriver.setup() fails during ping(), the redis client
    must be closed and EventBusConnectionError propagated.
    """
    driver = RedisStreamsDriver()
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=OSError("Connection refused"))
    mock_redis.aclose = AsyncMock()

    monkeypatch.setattr("redis.asyncio.Redis", MagicMock(return_value=mock_redis))

    with pytest.raises(EventBusConnectionError) as exc_info:
        await driver.setup()

    assert "Connection refused" in str(exc_info.value)
    assert driver._redis is None
    mock_redis.aclose.assert_awaited_once()

    # Repeated shutdown is safe
    await driver.shutdown()


async def test_event_bus_setup_failure_triggers_bus_shutdown(monkeypatch):
    """
    If driver.setup() fails inside EventBusTool.setup(), EventBusTool.shutdown()
    is triggered and the original error is re-raised.
    """
    tool = EventBusTool()
    mock_driver = MagicMock()
    mock_driver.setup = AsyncMock(side_effect=RuntimeError("Broker unavailable"))
    mock_driver.shutdown = AsyncMock()
    tool._driver = mock_driver

    with pytest.raises(RuntimeError) as exc_info:
        await tool.setup()

    assert "Broker unavailable" in str(exc_info.value)
    mock_driver.shutdown.assert_awaited_once()

    # Repeated shutdown is safe
    await tool.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# 4. RedisStateTool Lifecycle Cleanup
# ─────────────────────────────────────────────────────────────────────────────

async def test_redis_state_setup_failure_closes_client(monkeypatch):
    """
    If RedisStateTool.setup() fails during ping, the redis connection
    is closed before propagating StateConnectionError.
    """
    tool = RedisStateTool()
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=OSError("Redis down"))
    mock_redis.aclose = AsyncMock()

    monkeypatch.setattr("redis.asyncio.Redis", MagicMock(return_value=mock_redis))

    with pytest.raises(StateConnectionError):
        await tool.setup()

    assert tool._redis is None
    mock_redis.aclose.assert_awaited_once()

    # Repeated shutdown is safe
    await tool.shutdown()
