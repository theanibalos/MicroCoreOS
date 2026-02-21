import collections
import sys
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from core.base_tool import BaseTool


class EventBusTool(BaseTool):
    """
    Core Event Bus — Pub/Sub & Sync RPC.
    
    Clean, zero-boilerplate communication backbone for MicroCoreOS.
    Emitter is auto-detected from the caller's class (single frame lookup).
    
    Contract:
        publish(event_name, data)
        subscribe(event_name, callback)      # callback(data, event_name)
        unsubscribe(event_name, callback)
        request(event_name, data, timeout=5) -> response
        get_trace_history() -> list[dict]
    """

    def __init__(self):
        self._subscribers = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="BusWorker")
        self._trace_log = collections.deque(maxlen=500)
        self._local = threading.local()  # Thread-local for parent_id causality tracking

    @property
    def name(self) -> str:
        return "event_bus"

    def setup(self):
        print("[System] EventBusTool: Online.")

    def get_interface_description(self) -> str:
        return """
        Event Bus Tool (event_bus):
        - PURPOSE: Centralized pub/sub & RPC communication between plugins.
        - CAPABILITIES:
            - publish(event_name, data): Fire an asynchronous event. Emitter auto-detected.
            - subscribe(event_name, callback): Listen to events. Use '*' for all. Callback: callback(data, event_name).
            - unsubscribe(event_name, callback): Stop listening.
            - request(event_name, data, timeout=5): Synchronous RPC call. Returns the handler's return value.
            - get_trace_history(): Returns list of traced events for observability.
        """

    # ─── Public API ───────────────────────────────────────────

    def subscribe(self, event_name, callback):
        """Register a callback for an event. Use '*' to listen to all events."""
        with self._lock:
            self._subscribers.setdefault(event_name, []).append(callback)

    def unsubscribe(self, event_name, callback):
        """Remove a specific callback from an event."""
        with self._lock:
            if event_name in self._subscribers:
                self._subscribers[event_name] = [
                    cb for cb in self._subscribers[event_name] if cb is not callback
                ]
                if not self._subscribers[event_name]:
                    del self._subscribers[event_name]

    def publish(self, event_name, data):
        """
        Fire-and-forget event dispatch.
        Emitter is auto-detected from the caller. No boilerplate needed.
        """
        emitter = self._detect_caller()

        callbacks, wildcard_callbacks = self._collect_callbacks(event_name)

        event_id = str(uuid.uuid4())
        parent_id = getattr(self._local, 'current_event_id', None)

        all_callbacks = callbacks + wildcard_callbacks
        self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

        # Dispatch — no RPC reply routing for regular publish
        for cb in all_callbacks:
            self._executor.submit(self._dispatch, cb, data, event_name, event_id)

    def request(self, event_name, data, timeout=5):
        """
        Synchronous RPC over the EventBus.
        Publishes the event, waits for the first handler to return a value,
        and routes it back to the caller.
        """
        emitter = self._detect_caller()
        reply_event = f"reply.{event_name}.{uuid.uuid4().hex[:8]}"

        container = {"result": None}
        ready = threading.Event()

        def _reply_handler(reply_data, _event_name):
            container["result"] = reply_data
            ready.set()

        # Tag for trace subscriber name resolution
        _reply_handler._subscriber_name = emitter

        self.subscribe(reply_event, _reply_handler)
        try:
            callbacks, wildcard_callbacks = self._collect_callbacks(event_name)

            event_id = str(uuid.uuid4())
            parent_id = getattr(self._local, 'current_event_id', None)

            all_callbacks = callbacks + wildcard_callbacks
            self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

            # Only direct subscribers can produce RPC replies (not wildcard listeners)
            for cb in callbacks:
                self._executor.submit(
                    self._dispatch, cb, data, event_name, event_id,
                    reply_event=reply_event
                )
            for cb in wildcard_callbacks:
                self._executor.submit(self._dispatch, cb, data, event_name, event_id)

            if not ready.wait(timeout):
                raise TimeoutError(f"RPC Timeout: '{event_name}'")
            return container["result"]
        finally:
            self.unsubscribe(reply_event, _reply_handler)

    def get_trace_history(self):
        """Return a copy of the event trace log for dashboard/observability."""
        with self._lock:
            return list(self._trace_log)

    # ─── Internal ─────────────────────────────────────────────

    @staticmethod
    def _detect_caller():
        """
        Auto-detect who called publish/request.
        Uses sys._getframe(2) — single frame lookup, NOT a stack walk.
        Frame 0 = _detect_caller, Frame 1 = publish/request, Frame 2 = the actual caller.
        """
        try:
            frame = sys._getframe(2)
            caller_self = frame.f_locals.get('self')
            if caller_self is not None:
                return caller_self.__class__.__name__
        except (ValueError, AttributeError):
            pass
        return "Unknown"

    def _collect_callbacks(self, event_name):
        """Safely collect direct + wildcard callbacks under lock."""
        with self._lock:
            direct = list(self._subscribers.get(event_name, []))
            wildcard = list(self._subscribers.get('*', []))
        return direct, wildcard

    def _dispatch(self, callback, data, event_name, event_id, reply_event=None):
        """Execute a single callback in a worker thread."""
        self._local.current_event_id = event_id
        try:
            result = callback(data, event_name)

            # RPC auto-reply: if a reply_event is set and callback returned a value
            if reply_event is not None and result is not None:
                cb_name = self._get_subscriber_name(callback)
                # Publish reply — emitter detected as the callback's owner
                self._publish_reply(reply_event, result, cb_name)

        except Exception as e:
            cb_name = getattr(callback, "__name__", "callback")
            print(f"[EventBus] Error in {cb_name} for '{event_name}': {e}")
        finally:
            self._local.current_event_id = None

    def _publish_reply(self, event_name, data, emitter):
        """Internal publish for RPC replies — emitter is already known, no frame detection."""
        callbacks, wildcard_callbacks = self._collect_callbacks(event_name)

        event_id = str(uuid.uuid4())
        parent_id = getattr(self._local, 'current_event_id', None)

        all_callbacks = callbacks + wildcard_callbacks
        self._record_trace(event_id, parent_id, event_name, emitter, data, all_callbacks)

        for cb in all_callbacks:
            self._executor.submit(self._dispatch, cb, data, event_name, event_id)

    def _record_trace(self, event_id, parent_id, event_name, emitter, data, callbacks):
        """Record an event trace entry for observability."""
        subscribers = []
        for cb in callbacks:
            name = self._get_subscriber_name(cb)
            if name not in subscribers:
                subscribers.append(name)

        payload_keys = list(data.keys()) if isinstance(data, dict) else []

        with self._lock:
            self._trace_log.append({
                "id": event_id,
                "parent_id": parent_id,
                "timestamp": time.time(),
                "event_name": event_name,
                "emitter": emitter,
                "subscribers": subscribers,
                "payload_keys": payload_keys,
            })

    @staticmethod
    def _get_subscriber_name(callback):
        """Resolve the human-readable name of a callback. No stack inspection."""
        if hasattr(callback, '_subscriber_name'):
            return callback._subscriber_name
        if hasattr(callback, '__self__'):
            return callback.__self__.__class__.__name__
        if hasattr(callback, '__qualname__'):
            return callback.__qualname__.split('.')[0]
        return "func"

    def shutdown(self):
        self._executor.shutdown(wait=False)