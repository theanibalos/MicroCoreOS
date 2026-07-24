import asyncio
import pytest
from tools.sqlite.sqlite_tool import SqliteTool, DatabaseError

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def db(tmp_path):
    import os
    db_file = tmp_path / "test_concurrency.db"
    os.environ["SQLITE_DB_PATH"] = str(db_file)
    tool = SqliteTool()
    await tool.setup()
    yield tool
    await tool.shutdown()

async def test_sqlite_transaction_isolation(db):
    """
    Verify that concurrent transactions are isolated
    thanks to the new asyncio.Lock in SqliteTool.
    """
    await db.execute("CREATE TABLE IF NOT EXISTS counts (val INTEGER)")
    await db.execute("INSERT INTO counts VALUES (0)")

    async def increment_task(name, delay):
        async with db.transaction() as tx:
            # Read current value
            row = await tx.query_one("SELECT val FROM counts")
            val = row["val"]
            # Simulate delay to allow other tasks to try and enter
            await asyncio.sleep(delay)
            # Write new value
            await tx.execute("UPDATE counts SET val = $1", [val + 1])

    # Launch two concurrent tasks
    # Without Lock, both would read 0 and write 1.
    # With Lock, the second waits for the first to finish, reads 1, and writes 2.
    await asyncio.gather(
        increment_task("A", 0.1),
        increment_task("B", 0.05)
    )

    final_row = await db.query_one("SELECT val FROM counts")
    assert final_row["val"] == 2


async def test_db_execute_inside_transaction_joins_it_not_commits_early(db):
    """
    Regression test: calling the TOP-LEVEL db.execute() (instead of
    tx.execute()) from inside an open db.transaction() block must NOT
    commit anything early. Before the fix, _do_execute() unconditionally
    called self._db.commit() even when the reentrancy check detected we
    were already inside an outer transaction's SAVEPOINT — and SQLite's
    COMMIT closes the WHOLE underlying transaction regardless of how many
    SAVEPOINTs are open. That silently finalized the outer transaction
    early: a LATER failure in the same block would ROLLBACK TO SAVEPOINT
    against an already-committed connection, doing nothing, and every
    statement so far (including ones correctly issued via tx.execute())
    would survive the "rollback" instead of being undone.
    """
    await db.execute("CREATE TABLE IF NOT EXISTS accounts (name TEXT)")

    with pytest.raises(DatabaseError):
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO accounts (name) VALUES ($1)", ["via tx"])
            # Mistake a plugin could make: reaching for the injected `db`
            # instead of `tx` while inside the transaction block.
            await db.execute("INSERT INTO accounts (name) VALUES ($1)", ["via db"])
            raise DatabaseError("forced failure to trigger rollback")

    rows = await db.query("SELECT name FROM accounts")
    assert rows == [], (
        f"Expected the whole transaction to roll back (including the row "
        f"inserted via db.execute()), but found: {rows}"
    )
