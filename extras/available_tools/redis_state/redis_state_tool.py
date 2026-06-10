"""
Redis State Tool — Distributed replacement for the in-memory StateTool
======================================================================

Implements the state contract defined in `tools/state/state_tool.py`
(the REFERENCE IMPLEMENTATION) backed by Redis, so N replicas of
MicroCoreOS share counters, caches and rate-limit windows.

ACTIVATION (the swap — plugins are NOT touched):
─────────────────────────────────────────────────────────────────
    1. Move this folder into tools/:      mv extras/available_tools/redis_state tools/
    2. Move the in-memory tool out:       mv tools/state extras/available_tools/state
       (both declare name = "state"; only ONE may live in tools/ at a time)
    3. Uncomment the redis service in dev_infra/docker-compose.yml
    4. uv add "redis>=5.0"   (already in pyproject if this file shipped with the repo)

CONFIGURATION (env vars, read in __init__, zero I/O):
─────────────────────────────────────────────────────────────────
    REDIS_HOST              default "localhost"
    REDIS_PORT              default "6379"
    REDIS_DB                default "0"
    REDIS_PASSWORD          default "" (no auth)
    REDIS_CONNECT_TIMEOUT   default "5" (seconds)

CONTRACT MAPPING (from the reference header):
─────────────────────────────────────────────────────────────────
    namespace        → key prefix ("{namespace}:{key}")
    set + ttl        → SET key value PX ttl_ms
    get / has        → GET / EXISTS
    increment + ttl  → INCRBY (or INCRBYFLOAT) + PEXPIRE ttl_ms NX
    keys / get_all   → SCAN with prefix match
    delete / clear   → DEL / SCAN+DEL

VALUES are stored as JSON — which is why the contract requires
JSON-serializable values. get_all() returns fresh deserialized objects,
so the deep-copy guarantee of the reference holds by construction.

KNOWN SEMANTIC EDGE (documented divergence, PEXPIRE NX):
    If a key was created WITHOUT a TTL via set() and is later incremented
    WITH a ttl, the in-memory reference keeps it immortal while Redis
    attaches the TTL (NX = "only if no expiry exists", not "only if the
    key is new"). The fixed-window rate-limit pattern — increment-only
    keys — behaves identically in both implementations.
"""

import os
import json
import redis.asyncio as aioredis
from redis import exceptions as redis_exceptions
from core.base_tool import BaseTool, ToolUnavailableError


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXCEPTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class StateError(Exception):
    """Generic state error. Wraps redis exceptions."""
    pass


class StateConnectionError(StateError, ToolUnavailableError):
    """Connection error to the Redis server.

    Inherits ToolUnavailableError so ToolProxy marks the tool DEAD immediately
    (infrastructure failure), unlike plain StateError (likely business error).
    """
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REDIS STATE TOOL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RedisStateTool(BaseTool):
    """
    Distributed Key-Value State Tool backed by Redis.
    Drop-in replacement for the in-memory StateTool (same name: "state").
    """

    @property
    def name(self) -> str:
        return "state"

    def __init__(self) -> None:
        self._host: str = os.getenv("REDIS_HOST", "localhost")
        self._port: int = int(os.getenv("REDIS_PORT", "6379"))
        self._db: int = int(os.getenv("REDIS_DB", "0"))
        self._password: str = os.getenv("REDIS_PASSWORD", "")
        self._connect_timeout: float = float(os.getenv("REDIS_CONNECT_TIMEOUT", "5"))
        self._redis: aioredis.Redis | None = None

    # ─── LIFECYCLE ────────────────────────────────────────

    async def setup(self) -> None:
        print(f"[System] RedisStateTool: Connecting to {self._host}:{self._port}/{self._db}...")
        self._redis = aioredis.Redis(
            host=self._host,
            port=self._port,
            db=self._db,
            password=self._password or None,
            socket_connect_timeout=self._connect_timeout,
            socket_timeout=self._connect_timeout,
            decode_responses=True,
        )
        try:
            await self._redis.ping()
        except (redis_exceptions.RedisError, OSError) as e:
            raise StateConnectionError(
                f"Cannot connect to Redis at {self._host}:{self._port}/{self._db}: {e}"
            ) from e
        print("[System] RedisStateTool: Distributed store ready.")

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            print("[RedisStateTool] Connection closed.")

    def get_interface_description(self) -> str:
        return """
        Key-Value State Tool (state) — Redis-backed:
        - PURPOSE: Share volatile global data between plugins AND between replicas.
        - IDEAL FOR: Counters, temporary caches, rate-limit windows, business semaphores.
        - CONTRACT: All methods are async. Values must be JSON-serializable
          (they are stored as JSON in Redis).
        - TTL: optional expiry in seconds. Expired keys behave like missing keys.
          On increment(), the TTL only applies when the key is created (fixed window).
        - CAPABILITIES:
            - await set(key, value, namespace='default', ttl=None): Store a value.
            - await get(key, default=None, namespace='default'): Retrieve a value (None if missing).
            - await has(key, namespace='default'): Returns True if key exists.
            - await keys(namespace='default'): Returns list of all live keys in the namespace.
            - await get_all(namespace='default'): Returns a dict of all live key-value pairs.
            - await increment(key, amount=1, namespace='default', ttl=None): Atomic increment.
              Starts at 0. Returns the new value.
            - await delete(key, namespace='default'): Delete a key (no-op if missing).
            - await clear(namespace='default'): Remove all keys in the namespace.
        - EXCEPTIONS: Raises StateError or StateConnectionError on failure.
        """

    # ─── INTERNAL ─────────────────────────────────────────

    @staticmethod
    def _full_key(namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    @staticmethod
    def _ttl_ms(ttl: float | None) -> int | None:
        # PX/PEXPIRE take integer milliseconds; the contract allows float seconds.
        return max(1, round(ttl * 1000)) if ttl is not None else None

    @staticmethod
    def _wrap_infra(e: Exception) -> StateConnectionError:
        return StateConnectionError(f"Redis unreachable: {e}")

    # ─── PUBLIC API (state contract) ──────────────────────

    async def set(self, key: str, value, namespace: str = "default", ttl: float | None = None) -> None:
        try:
            payload = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise StateError(f"Value for key '{key}' is not JSON-serializable: {type(value).__name__}") from e
        try:
            await self._redis.set(self._full_key(namespace, key), payload, px=self._ttl_ms(ttl))
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e

    async def get(self, key: str, default=None, namespace: str = "default"):
        try:
            raw = await self._redis.get(self._full_key(namespace, key))
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e
        return default if raw is None else json.loads(raw)

    async def has(self, key: str, namespace: str = "default") -> bool:
        try:
            return await self._redis.exists(self._full_key(namespace, key)) == 1
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e

    async def keys(self, namespace: str = "default") -> list:
        prefix = f"{namespace}:"
        try:
            return [k[len(prefix):] async for k in self._redis.scan_iter(match=f"{prefix}*")]
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e

    async def get_all(self, namespace: str = "default") -> dict:
        prefix = f"{namespace}:"
        try:
            full_keys = [k async for k in self._redis.scan_iter(match=f"{prefix}*")]
            if not full_keys:
                return {}
            values = await self._redis.mget(full_keys)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e
        # A key may expire between SCAN and MGET → its value comes back None: skip it.
        return {
            k[len(prefix):]: json.loads(v)
            for k, v in zip(full_keys, values)
            if v is not None
        }

    async def increment(self, key: str, amount: int | float = 1,
                        namespace: str = "default", ttl: float | None = None) -> int | float:
        full_key = self._full_key(namespace, key)
        ttl_ms = self._ttl_ms(ttl)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                if isinstance(amount, float):
                    pipe.incrbyfloat(full_key, amount)
                else:
                    pipe.incrby(full_key, amount)
                if ttl_ms is not None:
                    pipe.pexpire(full_key, ttl_ms, nx=True)
                results = await pipe.execute()
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e
        except redis_exceptions.ResponseError as e:
            # INCRBY/INCRBYFLOAT on a non-numeric value — same error as the reference.
            raise ValueError(f"Key '{key}' is not numeric.") from e
        # json.loads turns "6" into int 6 and "6.5" into float 6.5,
        # matching the reference's int/float return types.
        return json.loads(str(results[0]))

    async def delete(self, key: str, namespace: str = "default") -> None:
        try:
            await self._redis.delete(self._full_key(namespace, key))
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e

    async def clear(self, namespace: str = "default") -> None:
        try:
            batch = []
            async for k in self._redis.scan_iter(match=f"{namespace}:*"):
                batch.append(k)
                if len(batch) >= 500:
                    await self._redis.delete(*batch)
                    batch = []
            if batch:
                await self._redis.delete(*batch)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as e:
            raise self._wrap_infra(e) from e

    async def health_check(self) -> bool:
        try:
            if self._redis is None:
                return False
            await self._redis.ping()
            return True
        except Exception:
            return False
