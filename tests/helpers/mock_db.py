"""Prefabricated mocks for the `db` tool's transaction context manager.

A bare `AsyncMock()` cannot stand in for `async with db.transaction() as tx:`
— calling any method on an `AsyncMock` returns a coroutine, which has no
`__aenter__`/`__aexit__`, so the test crashes with `TypeError: 'coroutine'
object does not support the asynchronous context manager protocol`. Building
the nested mock by hand is error-prone (the object bound by `as tx:` is
`__aenter__`'s return value, not `transaction.return_value`), so these
classes package the two cases tests actually need.

`transaction()` is a *sync* method returning an async context manager, so it
must be overridden with `MagicMock` — never left as an `AsyncMock` attribute:

    db = AsyncMock()
    db.transaction = MagicMock(return_value=TxMock())         # happy path
    db.transaction = MagicMock(return_value=FailingTxMock())  # sad path
"""
from unittest.mock import AsyncMock


class TxMock:
    """Transaction that enters cleanly; every tx method is an AsyncMock, so
    tests stub return values and assert awaits on the instance itself:

        tx = TxMock()
        tx.execute.return_value = 1
        db.transaction = MagicMock(return_value=tx)
        # ... exercise the plugin ...
        tx.execute.assert_awaited_with("INSERT INTO ...", [...])
    """

    def __init__(self) -> None:
        self.query = AsyncMock()
        self.query_one = AsyncMock()
        self.execute = AsyncMock()

    async def __aenter__(self) -> "TxMock":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False


class FailingTxMock:
    """Transaction whose every operation raises — for sad paths (rollback,
    DLQ). The context manager itself enters and exits cleanly; the failure
    happens inside the block, exactly like a real query error would.
    """

    def __init__(self, error_msg: str = "forced failure") -> None:
        self.err = RuntimeError(error_msg)

    async def __aenter__(self) -> "FailingTxMock":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    async def query(self, *args, **kwargs):
        raise self.err

    async def query_one(self, *args, **kwargs):
        raise self.err

    async def execute(self, *args, **kwargs):
        raise self.err
