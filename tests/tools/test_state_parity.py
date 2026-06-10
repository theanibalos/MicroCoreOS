"""
State contract parity suite (Issue 22 pattern).

Every tool that registers as "state" MUST pass this battery — it is the
executable version of the contract written in tools/state/state_tool.py.
The suite runs parametrized over all known implementations:

    - memory: the in-memory reference (always runs)
    - redis:  RedisStateTool (skips itself if no Redis server is reachable;
              start one with: docker compose -f dev_infra/docker-compose.yml up -d redis)

Timings are looser than tests/test_state_tool.py because here TTLs travel
over a real network instead of resolving in-process.
"""

import asyncio
import pytest
from tools.state.state_tool import StateTool
from extras.available_tools.redis_state.redis_state_tool import (
    RedisStateTool,
    StateConnectionError,
)

pytestmark = pytest.mark.anyio

# Namespaces touched by this battery — wiped before/after each Redis test
# so runs are hermetic even against a shared dev server.
NAMESPACES = ("default", "a", "b")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["memory", "redis"])
async def tool(request, monkeypatch):
    if request.param == "memory":
        yield StateTool()
        return

    # Keep test keys away from dev data (db 0).
    monkeypatch.setenv("REDIS_DB", "15")
    t = RedisStateTool()
    try:
        await t.setup()
    except StateConnectionError:
        pytest.skip("Redis not available — docker compose -f dev_infra/docker-compose.yml up -d redis")
    for ns in NAMESPACES:
        await t.clear(ns)
    yield t
    for ns in NAMESPACES:
        await t.clear(ns)
    await t.shutdown()


# ─── Basic key-value ──────────────────────────────────────────────────────────

async def test_set_and_get(tool):
    await tool.set("x", 42)
    assert await tool.get("x") == 42


async def test_get_missing_key_returns_default(tool):
    assert await tool.get("missing") is None
    assert await tool.get("missing", default="fallback") == "fallback"


async def test_has(tool):
    assert await tool.has("x") is False
    await tool.set("x", 1)
    assert await tool.has("x") is True


async def test_keys(tool):
    await tool.set("a", 1)
    await tool.set("b", 2)
    assert sorted(await tool.keys()) == ["a", "b"]


async def test_json_values_roundtrip(tool):
    value = {"name": "Ana", "tags": ["a", "b"], "active": True, "score": 1.5, "meta": None}
    await tool.set("doc", value)
    assert await tool.get("doc") == value


async def test_get_all_is_a_copy(tool):
    await tool.set("k", [1, 2, 3])
    snapshot = await tool.get_all()
    snapshot["new_key"] = 99
    assert await tool.has("new_key") is False


async def test_get_all_deep_copy_protects_mutable_values(tool):
    await tool.set("k", [1, 2, 3])
    snapshot = await tool.get_all()
    snapshot["k"].append(99)
    assert await tool.get("k") == [1, 2, 3]


# ─── Increment ────────────────────────────────────────────────────────────────

async def test_increment_from_zero(tool):
    assert await tool.increment("counter") == 1
    assert await tool.increment("counter") == 2


async def test_increment_custom_amount(tool):
    assert await tool.increment("counter", amount=5) == 5
    assert await tool.increment("counter", amount=3) == 8


async def test_increment_float_amount(tool):
    assert await tool.increment("score", amount=1.5) == 1.5


async def test_increment_non_numeric_raises(tool):
    await tool.set("s", "text")
    with pytest.raises(ValueError):
        await tool.increment("s")


async def test_concurrent_increments(tool):
    await asyncio.gather(*[tool.increment("hits") for _ in range(50)])
    assert await tool.get("hits") == 50


# ─── Delete / clear / namespaces ──────────────────────────────────────────────

async def test_delete(tool):
    await tool.set("x", 1)
    await tool.delete("x")
    assert await tool.has("x") is False


async def test_delete_missing_key_no_error(tool):
    await tool.delete("nonexistent")


async def test_clear(tool):
    await tool.set("a", 1)
    await tool.set("b", 2)
    await tool.clear()
    assert await tool.keys() == []


async def test_namespace_isolation(tool):
    await tool.set("x", 1, namespace="a")
    assert await tool.get("x", namespace="b") is None
    await tool.clear(namespace="b")
    assert await tool.get("x", namespace="a") == 1


# ─── TTL (fixed-window semantics) ─────────────────────────────────────────────

async def test_ttl_key_expires(tool):
    await tool.set("temp", "v", ttl=0.1)
    assert await tool.get("temp") == "v"
    await asyncio.sleep(0.15)
    assert await tool.get("temp") is None
    assert await tool.has("temp") is False


async def test_ttl_none_never_expires(tool):
    await tool.set("perm", "v")
    await asyncio.sleep(0.1)
    assert await tool.get("perm") == "v"


async def test_expired_key_excluded_from_keys_and_get_all(tool):
    await tool.set("temp", 1, ttl=0.1)
    await tool.set("perm", 2)
    await asyncio.sleep(0.15)
    assert await tool.keys() == ["perm"]
    assert await tool.get_all() == {"perm": 2}


async def test_increment_ttl_applies_only_on_creation(tool):
    """Fixed window: the TTL set at creation is NOT extended by later increments."""
    await tool.increment("attempts", ttl=0.2)
    await asyncio.sleep(0.12)
    await tool.increment("attempts", ttl=0.2)  # must NOT reset the window
    assert await tool.get("attempts") == 2
    await asyncio.sleep(0.12)  # 0.24 total > 0.2 original window
    assert await tool.get("attempts") is None


async def test_increment_after_expiry_restarts_from_zero(tool):
    await tool.increment("attempts", ttl=0.1)
    await asyncio.sleep(0.15)
    assert await tool.increment("attempts", ttl=0.1) == 1
