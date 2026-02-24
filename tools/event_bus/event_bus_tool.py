import collections
import sys
import time
import uuid
import asyncio
import inspect
import contextvars
from core.base_tool import BaseTool
from core.context import current_event_id_var, current_identity_var

class EventBusTool(BaseTool):
    """
    Async-Native Event Bus — Pub/Sub & Async RPC.
    Supports both sync and async subscribers.
    """

    def __init__(self):
        self._subscribers = {}
        self._lock = asyncio.Lock()
        self._trace_log = collections.deque(maxlen=500)

    @property
    def name(self) -> str:
        return "event_bus"

    async def setup(self):
        print("[System] EventBusTool: Online (Async).")

    def get_interface_description(self) -> str:
        return """
        Async Event Bus Tool (event_bus):
        - PURPOSE: High-performance, non-blocking communication between plugins using Pub/Sub and Async RPC.
        - CAPABILITIES:
            - await publish(event_name, data): Broadcasts an event. Fire-and-forget.
            - await subscribe(event_name, callback): Listens for a specific event. Callback can be async or sync.
            - await request(event_name, data, timeout=5): Performs an Asynchronous RPC. Waits for a response from a subscriber.
        - TRACING: Tracks event causality across the system for observability.
        """

    async def subscribe(self, event_name, callback):
        async with self._lock:
            self._subscribers.setdefault(event_name, []).append(callback)

    async def unsubscribe(self, event_name, callback):
        async with self._lock:
            if event_name in self._subscribers:
                self._subscribers[event_name] = [
                    cb for cb in self._subscribers[event_name] if cb is not callback
                ]
                if not self._subscribers[event_name]:
                    del self._subscribers[event_name]

    async def publish(self, event_name, data):
        emitter = self._detect_caller()
        callbacks, wildcard_callbacks = await self._collect_callbacks(event_name)

        event_id = str(uuid.uuid4())
        parent_id = current_event_id_var.get()

        all_callbacks = callbacks + wildcard_callbacks
        self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

        for cb in all_callbacks:
            # Dispatch as a task to avoid blocking the caller
            task = asyncio.create_task(self._dispatch(cb, data, event_name, event_id))
            # Automated Core Monitoring: Watch for background task failures
            self._attach_monitoring(task, event_name, cb)

    async def request(self, event_name, data, timeout=5):
        emitter = self._detect_caller()
        reply_event = f"reply.{event_name}.{uuid.uuid4().hex[:8]}"

        future = asyncio.get_running_loop().create_future()

        async def _reply_handler(reply_data, _event_name):
            if not future.done():
                future.set_result(reply_data)

        _reply_handler._subscriber_name = emitter

        await self.subscribe(reply_event, _reply_handler)
        try:
            callbacks, wildcard_callbacks = await self._collect_callbacks(event_name)

            event_id = str(uuid.uuid4())
            parent_id = current_event_id_var.get()

            all_callbacks = callbacks + wildcard_callbacks
            self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

            for cb in callbacks:
                task = asyncio.create_task(
                    self._dispatch(cb, data, event_name, event_id, reply_event=reply_event)
                )
                self._attach_monitoring(task, event_name, cb)

            for cb in wildcard_callbacks:
                task = asyncio.create_task(self._dispatch(cb, data, event_name, event_id))
                self._attach_monitoring(task, event_name, cb)

            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            await self.unsubscribe(reply_event, _reply_handler)

    def get_trace_history(self):
        return list(self._trace_log)

    async def _collect_callbacks(self, event_name):
        async with self._lock:
            direct = list(self._subscribers.get(event_name, []))
            wildcard = list(self._subscribers.get('*', []))
        return direct, wildcard

    async def _dispatch(self, callback, data, event_name, event_id, reply_event=None):
        # Set the identity and causality context
        subscriber_name = self._get_subscriber_name(callback)
        id_token = current_event_id_var.set(event_id)
        ident_token = current_identity_var.set(subscriber_name)
        
        try:
            if inspect.iscoroutinefunction(callback):
                result = await callback(data, event_name)
            else:
                # Still use threadpool for sync callbacks to avoid blocking the bus
                from starlette.concurrency import run_in_threadpool
                result = await run_in_threadpool(callback, data, event_name)

            if reply_event is not None and result is not None:
                cb_name = self._get_subscriber_name(callback)
                await self._publish_reply(reply_event, result, cb_name)

        except Exception as e:
            cb_name = self._get_subscriber_name(callback)
            print(f"[EventBus] Error in {cb_name} for '{event_name}': {e}")
        finally:
            current_event_id_var.reset(id_token)
            current_identity_var.reset(ident_token)

    async def _publish_reply(self, event_name, data, emitter):
        callbacks, wildcard_callbacks = await self._collect_callbacks(event_name)
        event_id = str(uuid.uuid4())
        parent_id = current_event_id_var.get()

        all_callbacks = callbacks + wildcard_callbacks
        self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

        for cb in all_callbacks:
            task = asyncio.create_task(self._dispatch(cb, data, event_name, event_id))
            self._attach_monitoring(task, event_name, cb)

    def _record_trace(self, event_id, parent_id, event_name, emitter, data, callbacks):
        subscribers = [self._get_subscriber_name(cb) for cb in callbacks]
        payload_keys = list(data.keys()) if isinstance(data, dict) else []

        # Trace log can be updated without lock if we use a thread-safe structure,
        # but in a single-threaded loop, simple append is fine.
        trace_data = {
            "id": event_id,
            "parent_id": parent_id,
            "timestamp": time.time(),
            "event_name": event_name,
            "emitter": emitter,
            "subscribers": list(set(subscribers)),
            "payload_keys": payload_keys,
        }
        self._trace_log.append(trace_data)
        
        # PERSISTENCE: Print to stdout so it's captured in system.log
        # This acts as an "anótación" that survives crashes.
        print(f"[EventBus] 📣 Event Published: {event_name} (ID: {event_id[:8]}, Parent: {str(parent_id)[:8] if parent_id else 'None'}, Emitter: {emitter})")

    def _detect_caller(self):
        """
        Detects the identity of the caller using ContextVars.
        This replaces fragile stack frame inspection.
        """
        return current_identity_var.get()

    def _attach_monitoring(self, task, event_name, callback):
        """Attaches a callback to report background failures to the Registry."""
        name = self._get_subscriber_name(callback)
        def _on_done(t):
            try:
                t.result()
            except Exception as e:
                # We can't import Container/Registry directly to avoid Tool-Tool coupling,
                # but we can try to use a global hook or assume the task log is enough.
                # However, the user said it's OK for metrics. 
                # To keep it decoupled, we'll just log it for now as the ToolProxy 
                # already handles Tool-level crashes.
                # If we want the Registry to know, we'd need the Registry passed in setup.
                print(f"[EventBus/ERROR] Task failed in subscriber '{name}' for event '{event_name}': {e}")
        task.add_done_callback(_on_done)

    def _get_subscriber_name(self, callback):
        if hasattr(callback, '_subscriber_name'):
            return callback._subscriber_name
        if hasattr(callback, '__self__'):
            return f"{callback.__self__.__class__.__name__}.{callback.__name__}"
        if hasattr(callback, '__qualname__'):
            return callback.__qualname__
        return "func"

    async def shutdown(self):
        pass