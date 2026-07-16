"""Black-box tests for LogoutPlugin (stateless JWT logout: clears the cookie)."""
from unittest.mock import MagicMock

import pytest

from domains.users.plugins.logout_plugin import LogoutPlugin

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_logout_clears_access_token_cookie():
    plugin = LogoutPlugin(http=MagicMock(), logger=MagicMock())
    context = MagicMock()

    result = await plugin.execute({}, context)

    assert result["success"] is True
    context.set_cookie.assert_called_once_with("access_token", "", max_age=0)


async def test_logout_without_context_still_succeeds():
    plugin = LogoutPlugin(http=MagicMock(), logger=MagicMock())

    result = await plugin.execute({}, context=None)

    assert result["success"] is True
