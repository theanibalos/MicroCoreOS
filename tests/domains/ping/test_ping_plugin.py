"""Black-box tests for PingPlugin — the minimal no-DB plugin example."""
import pytest
from unittest.mock import MagicMock

from domains.ping.plugins.ping_plugin import PingPlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_ping_returns_pong_envelope():
    plugin = PingPlugin(logger=MagicMock(), http=MagicMock())
    result = await plugin.execute({})
    assert result["success"] is True
    assert result["data"] == {"status": "ok", "message": "pong"}


async def test_on_boot_registers_public_ping_route():
    http = MagicMock()
    plugin = PingPlugin(logger=MagicMock(), http=http)
    await plugin.on_boot()

    http.add_endpoint.assert_called_once()
    kwargs = http.add_endpoint.call_args.kwargs
    assert kwargs["path"] == "/ping"
    assert kwargs["method"] == "GET"
    assert "auth_validator" not in kwargs  # public by design
