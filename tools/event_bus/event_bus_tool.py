"""
Enterprise Event Bus — Universal Elastic Monolith Core
======================================================
Definitive Version: Pydantic-native traceability and industrial drivers.

UNIVERSAL HINTS (kwargs):
- key: String. Strict ordering (Kafka/SQS).
- priority: Integer (1-10). Importance (RabbitMQ).
- delay: Integer (seconds). Delivery schedule.
- ttl: Float (seconds). Message expiration (Broker-side).
- correlation_id: String. RPC tracking.
"""

import collections
import uuid
import asyncio
import inspect
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Dict, List, Tuple, Set
from pydantic import BaseModel, Field, ConfigDict
from starlette.concurrency import run_in_threadpool
from core.base_tool import BaseTool
from core.context import current_event_id_var, current_identity_var


class EventEnvelope(BaseModel):
    """The Universal Contract for any message traveling through the system."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event: str
    payload: Dict[str, Any]
    emitter: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    parent_id: Optional[str] = None
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    
    key: Optional[str] = None       
    priority: Optional[int] = None  
    delay: Optional[int] = None     
    ttl: Optional[float] = None     
    headers: Dict[str, Any] = Field(default_factory=dict)


class TraceNode(BaseModel):
    """Rich record for observability, capturing both publication and delivery events."""
    kind: str  # "published" or "delivered"
    envelope: EventEnvelope
    subscribers: List[str] = Field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    attempts: Optional[int] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TraceRecord(TraceNode):
    """Legacy compatibility alias for TraceNode."""
    pass


class SubOptions(BaseModel):
    """Configuration for a specific subscription."""
    retries: int = 0
    backoff: float = 0.5


class EventBusDriver:
    """Interface for all transport implementations (Translators)."""
    async def setup(self): pass
    def bind(self, deliver_hook: Callable):
        """Injected by the Bus to handle message delivery."""
        self._deliver_hook = deliver_hook

    async def publish(self, envelope: EventEnvelope) -> None: 
        """Pure fire-and-forget transport. Returns nothing."""
        raise NotImplementedError()

    async def subscribe(self, event_name: str, group: Optional[str], callback: Callable): raise NotImplementedError()
    async def unsubscribe(self, event_name: str, callback: Callable): raise NotImplementedError()
    async def unsubscribe_all(self, callback: Callable): raise NotImplementedError()
    def get_status(self, name_resolver: Callable) -> dict: return {"status": "abstract"}
    async def shutdown(self): pass


class InProcessDriver(EventBusDriver):
    """Memory transport. Simulates groups and handles internal delays."""
    def __init__(self):
        self._groups: Dict[str, Dict[Optional[str], List[Callable]]] = {}
        self._indices: Dict[str, Dict[Optional[str], int]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, envelope: EventEnvelope) -> None:
        # 1. Transport Delay (if any)
        if envelope.delay and envelope.delay > 0:
            await asyncio.sleep(envelope.delay)

        # 2. Resolve Targets (Logic moved to Driver side)
        targets = []
        async with self._lock:
            if envelope.event in self._groups:
                for group_name, callbacks in self._groups[envelope.event].items():
                    if not callbacks: continue
                    if group_name is None:
                        targets.extend([(cb, False) for cb in callbacks])
                    else:
                        idx = self._indices[envelope.event].get(group_name, 0)
                        targets.append((callbacks[idx % len(callbacks)], False))
                        self._indices[envelope.event][group_name] = (idx + 1) % len(callbacks)
            
            if "*" in self._groups:
                for callbacks in self._groups["*"].values():
                    targets.extend([(cb, True) for cb in callbacks])
        
        # 3. Trigger Delivery Hook (Inversion of Control)
        for cb, is_wildcard in targets:
            # We don't await here; the driver schedules the delivery
            asyncio.create_task(self._deliver_hook(envelope, cb, is_wildcard))

    async def subscribe(self, event_name: str, group: Optional[str], callback: Callable):
        async with self._lock:
            self._groups.setdefault(event_name, {}).setdefault(group, []).append(callback)
            self._indices.setdefault(event_name, {}).setdefault(group, 0)

    async def unsubscribe(self, event_name: str, callback: Callable):
        async with self._lock:
            self._remove_callback(event_name, callback)

    async def unsubscribe_all(self, callback: Callable):
        async with self._lock:
            for event in list(self._groups.keys()):
                self._remove_callback(event, callback)

    def _remove_callback(self, event_name: str, callback: Callable):
        group_map = self._groups.get(event_name)
        if not group_map: return
        for g_name in list(group_map.keys()):
            group_map[g_name] = [cb for cb in group_map[g_name] if cb != callback]
            if not group_map[g_name]:
                del group_map[g_name]
                if event_name in self._indices and g_name in self._indices[event_name]:
                    del self._indices[event_name][g_name]
        if not group_map:
            del self._groups[event_name]

    def get_status(self, name_resolver: Callable) -> dict:
        return {
            event: [name_resolver(cb) for g in groups.values() for cb in g] 
            for event, groups in self._groups.items()
        }


class EventBusTool(BaseTool):
    _MAX_CONSECUTIVE_FAILURES = 5

    def __init__(self, driver: Optional[EventBusDriver] = None):
        self._driver = driver or InProcessDriver()
        self._trace_log: collections.deque = collections.deque(maxlen=500)
        self._listeners: list = []
        self._failure_listeners: list = []
        self._consecutive_failures: dict[tuple[str, str], int] = {}
        self._pending_tasks: Set[asyncio.Task] = set()
        self._sub_options: Dict[Tuple[str, Callable], SubOptions] = {}
        
        # Bind the delivery hook
        self._driver.bind(self._deliver)

    @property
    def name(self) -> str: return "event_bus"

    async def setup(self) -> None:
        await self._driver.setup()
        print(f"[System] EventBusTool: Online (Universal Driver: {self._driver.__class__.__name__}).")

    def get_interface_description(self) -> str:
        return """
        Universal Event Bus (event_bus):
        - publish(event_name, data, **kwargs): Broadcast an event.
        - subscribe(event_name, callback, group=None, retries=0, backoff=0.5): Listen for events.
        - request(event_name, data, timeout=5): Async RPC (returns dict).
        - unsubscribe(event_name, callback): Stop listening.
        - get_trace_history() -> List[TraceNode]: Last 500 event records.
        - get_subscribers() -> dict: Current subscriber map.
        - add_listener(callback): Sink for all events (record: dict).
        - add_failure_listener(callback): Sink for errors (record: dict).
        
        CRITICAL: Subscribing callbacks receive an 'EventEnvelope' object.
        Example: async def on_event(self, event: EventEnvelope): print(event.payload)
        
        RETRIES & IDEMPOTENCY:
        - If 'retries' > 0, the handler will be re-executed on failure with exponential backoff.
        - Ensure handlers are idempotent as they may run multiple times.

        DEAD-LETTER QUEUE (DLQ):
        - Final failures are published to '_dlq.<original_event>'.
        - Payload includes 'original' envelope, 'subscriber', 'error', and 'attempts'.
        - Loop protection: '_dlq.*', '_reply.*', and wildcard events are never dead-lettered.
        - Toggle via EVENT_BUS_DLQ_ENABLED (default: true).

        UNIVERSAL CAPABILITIES (kwargs):
        - key: String. For strict ordering (Kafka/SQS).
        - priority: Integer (1-10). Importance (RabbitMQ).
        - delay: Integer (seconds). Delivery schedule.
        - ttl: Float (seconds). Message expiration hint.
        - correlation_id: String. Cross-reference for RPC.

        RESILIENCE:
        - A subscriber that reaches 5 consecutive FINAL failures for a specific event is auto-unsubscribed.
        """

    async def subscribe(self, event_name: str, callback: Callable, group: Optional[str] = None, retries: int = 0, backoff: float = 0.5):
        self._sub_options[(event_name, callback)] = SubOptions(retries=retries, backoff=backoff)
        await self._driver.subscribe(event_name, group, callback)

    async def unsubscribe(self, event_name: str, callback: Callable):
        for key in list(self._sub_options.keys()):
            if key[1] == callback:
                del self._sub_options[key]
        await self._driver.unsubscribe(event_name, callback)

    async def publish(self, event_name: str, data: dict, **kwargs):
        kwargs.pop("emitter", None)
        envelope = EventEnvelope(
            event=event_name, payload=data,
            emitter=current_identity_var.get() or "system",
            parent_id=current_event_id_var.get(),
            **kwargs
        )
        
        # 1. Record Publication (Tracing)
        # Note: In a distributed system, we don't know the subscribers yet.
        record = TraceNode(kind="published", envelope=envelope)
        self._trace_log.append(record)
        
        raw_record = {
            **envelope.model_dump(), 
            "kind": "published",
            "payload_keys": list(envelope.payload.keys()),
            "timestamp": envelope.timestamp.timestamp()
        }
        for l in self._listeners: 
            try: 
                res = l(raw_record)
                if inspect.isawaitable(res):
                    task = asyncio.create_task(res)
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
            except Exception: pass
        
        print(f"[EventBus] 📣 {envelope.event} [{envelope.id[:8]}]")

        # 2. Hand over to Driver (Fire and Forget)
        task = asyncio.create_task(self._driver.publish(envelope))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def request(self, event_name: str, data: dict, timeout: float = 5):
        correlation_id = str(uuid.uuid4())
        reply_to = f"_reply.{event_name}.{uuid.uuid4().hex[:8]}"
        future = asyncio.get_running_loop().create_future()
        
        async def _collector(env: EventEnvelope):
            if env.correlation_id == correlation_id and not future.done():
                future.set_result(env.payload)
        
        await self.subscribe(reply_to, _collector)
        try:
            await self.publish(event_name, data, reply_to=reply_to, correlation_id=correlation_id)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            await self.unsubscribe(reply_to, _collector)

    # ── Internal Engine ─────────────────────────────────────────────────────────

    async def _deliver(self, envelope: EventEnvelope, callback: Callable, is_wildcard: bool):
        """Entry point for message delivery, triggered by the Driver."""
        task = asyncio.create_task(self._do_deliver(envelope, callback, is_wildcard))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _do_deliver(self, envelope: EventEnvelope, callback: Callable, is_wildcard: bool):
        sub_name = self._get_name(callback)
        
        # Feature 1: TTL Check
        if envelope.ttl is not None:
            age = (datetime.now(timezone.utc) - envelope.timestamp).total_seconds()
            if age > envelope.ttl:
                node = TraceNode(
                    kind="delivered", envelope=envelope, subscribers=[sub_name],
                    success=False, error="ttl_expired", attempts=0
                )
                self._trace_log.append(node)
                return

        # Feature 2: Resolve Subscription Options
        options = self._sub_options.get((envelope.event, callback))
        if not options and is_wildcard:
            options = self._sub_options.get(("*", callback))
        options = options or SubOptions()

        t1 = current_event_id_var.set(envelope.id)
        t2 = current_identity_var.set(sub_name)
        
        success = False
        last_error = None
        attempts = 0
        
        try:
            # Retry Loop
            while attempts <= options.retries:
                attempts += 1
                try:
                    if inspect.iscoroutinefunction(callback):
                        result = await callback(envelope)
                    else:
                        result = await run_in_threadpool(callback, envelope)

                    if not is_wildcard and envelope.reply_to and result is not None:
                        await self.publish(
                            envelope.reply_to, 
                            result if isinstance(result, dict) else {"result": result},
                            correlation_id=envelope.correlation_id
                        )
                    
                    success = True
                    self._consecutive_failures.pop((sub_name, envelope.event), None)
                    break
                except Exception as e:
                    last_error = e
                    if attempts <= options.retries:
                        wait = options.backoff * (2 ** (attempts - 1))
                        await asyncio.sleep(wait)
            
            # Record Trace Node (delivered)
            node = TraceNode(
                kind="delivered", envelope=envelope, subscribers=[sub_name],
                success=success, error=str(last_error) if not success else None,
                attempts=attempts
            )
            self._trace_log.append(node)

            if not success:
                await self._handle_final_failure(last_error, sub_name, envelope, callback, attempts, is_wildcard)

        finally:
            current_event_id_var.reset(t1)
            current_identity_var.reset(t2)

    async def _handle_final_failure(self, e, sub_name, envelope, callback, attempts, is_wildcard):
        # Poisoned-handler logic
        fail_key = (sub_name, envelope.event)
        count = self._consecutive_failures.get(fail_key, 0) + 1
        self._consecutive_failures[fail_key] = count
        print(f"[EventBus] 💥 Final failure in {sub_name} for event {envelope.event}: {e} ({count}/{self._MAX_CONSECUTIVE_FAILURES})")
        
        if count >= self._MAX_CONSECUTIVE_FAILURES:
            self._consecutive_failures.pop(fail_key, None)
            await self._driver.unsubscribe(envelope.event, callback)
            self._sub_options.pop((envelope.event, callback), None)

        # Notify failure listeners
        failure_record = {"event": envelope.event, "event_id": envelope.id, "subscriber": sub_name, "error": str(e), "attempts": attempts}
        for fl in self._failure_listeners:
            try: 
                res = fl(failure_record)
                if inspect.isawaitable(res):
                    task = asyncio.create_task(res)
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
            except Exception: pass

        # Feature 3: Dead-Letter Queue (DLQ)
        if not envelope.event.startswith(("_dlq.", "_reply.")) and not is_wildcard:
            if os.getenv("EVENT_BUS_DLQ_ENABLED", "true").lower() == "true":
                dlq_payload = {
                    "original": envelope.model_dump(mode="json"),
                    "subscriber": sub_name,
                    "error": str(e),
                    "attempts": attempts,
                    "failed_at": datetime.now(timezone.utc).isoformat()
                }
                await self.publish(f"_dlq.{envelope.event}", dlq_payload, correlation_id=envelope.correlation_id)

    def get_trace_history(self) -> List[TraceNode]: return list(self._trace_log)
    def add_listener(self, cb): self._listeners.append(cb)
    def add_failure_listener(self, cb): self._failure_listeners.append(cb)

    def _get_name(self, cb):
        if hasattr(cb, "__self__"): return f"{cb.__self__.__class__.__name__}.{cb.__name__}"
        return getattr(cb, "__qualname__", "anonymous")

    def get_subscribers(self) -> dict:
        return self._driver.get_status(name_resolver=self._get_name)

    async def shutdown(self):
        if self._pending_tasks:
            print(f"[EventBus] Cleaning up {len(self._pending_tasks)} pending tasks...")
            for task in self._pending_tasks:
                task.cancel()
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        await self._driver.shutdown()
