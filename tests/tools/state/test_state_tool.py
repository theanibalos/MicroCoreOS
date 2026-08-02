import asyncio
import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_set_and_get(state):
    await state.set("x", 42)
    assert await state.get("x") == 42


async def test_get_missing_key_returns_default(state):
    assert await state.get("missing") is None
    assert await state.get("missing", default="fallback") == "fallback"


async def test_has(state):
    assert await state.has("x") is False
    await state.set("x", 1)
    assert await state.has("x") is True


async def test_keys(state):
    await state.set("a", 1)
    await state.set("b", 2)
    assert sorted(await state.keys()) == ["a", "b"]


async def test_get_all_is_a_copy(state):
    await state.set("k", [1, 2, 3])
    snapshot = await state.get_all()
    snapshot["new_key"] = 99
    assert await state.has("new_key") is False


async def test_get_all_deep_copy_protects_mutable_values(state):
    await state.set("k", [1, 2, 3])
    snapshot = await state.get_all()
    snapshot["k"].append(99)
    assert await state.get("k") == [1, 2, 3]


async def test_increment_from_zero(state):
    assert await state.increment("counter") == 1
    assert await state.increment("counter") == 2


async def test_increment_non_numeric_raises(state):
    await state.set("s", "text")
    with pytest.raises(ValueError):
        await state.increment("s")


async def test_delete(state):
    await state.set("x", 1)
    await state.delete("x")
    assert await state.has("x") is False


async def test_delete_missing_key_no_error(state):
    await state.delete("nonexistent")


async def test_clear(state):
    await state.set("a", 1)
    await state.set("b", 2)
    await state.clear()
    assert await state.keys() == []


async def test_namespace_isolation(state):
    await state.set("x", 1, namespace="a")
    assert await state.get("x", namespace="b") is None


async def test_concurrent_increments(state):
    await asyncio.gather(*[state.increment("hits") for _ in range(50)])
    assert await state.get("hits") == 50


async def test_increment_custom_amount(state):
    result = await state.increment("counter", amount=5)
    assert result == 5
    result = await state.increment("counter", amount=3)
    assert result == 8


async def test_increment_float_amount(state):
    result = await state.increment("score", amount=1.5)
    assert result == 1.5


# ─── TTL (fixed-window semantics, Redis-compatible) ──────────────────────────

async def test_ttl_key_expires(state):
    await state.set("temp", "v", ttl=0.05)
    assert await state.get("temp") == "v"
    await asyncio.sleep(0.08)
    assert await state.get("temp") is None
    assert await state.has("temp") is False


async def test_ttl_none_never_expires(state):
    await state.set("perm", "v")
    await asyncio.sleep(0.05)
    assert await state.get("perm") == "v"


async def test_expired_key_excluded_from_keys_and_get_all(state):
    await state.set("temp", 1, ttl=0.05)
    await state.set("perm", 2)
    await asyncio.sleep(0.08)
    assert await state.keys() == ["perm"]
    assert await state.get_all() == {"perm": 2}


async def test_increment_ttl_applies_only_on_creation(state):
    """Fixed window: the TTL set at creation is NOT extended by later increments."""
    await state.increment("attempts", ttl=0.1)
    await asyncio.sleep(0.06)
    await state.increment("attempts", ttl=0.1)  # must NOT reset the window
    assert await state.get("attempts") == 2
    await asyncio.sleep(0.06)  # 0.12 total > 0.1 original window
    assert await state.get("attempts") is None


async def test_increment_after_expiry_restarts_from_zero(state):
    await state.increment("attempts", ttl=0.05)
    await asyncio.sleep(0.08)
    assert await state.increment("attempts", ttl=0.05) == 1
