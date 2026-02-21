import collections
import time
import inspect
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from core.base_tool import BaseTool

class EventBusTool(BaseTool):
    def __init__(self):
        self._subscribers = {}
        self._lock = threading.Lock()
        # Create a thread pool to process events without saturating the system
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="BusWorker")
        # Internal tracer for debugging and visualization
        self._tracer_log = collections.deque(maxlen=500) # Increased to keep more history including logs
        self._local = threading.local()

    @property
    def name(self) -> str:
        return "event_bus"

    def get_trace_history(self):
        """Returns the chronological history of the last 100 events."""
        with self._lock:
            return list(self._tracer_log)

    def setup(self):
        print("[System] EventBusTool: Ready to orchestrate events with ThreadPool (max=10).")

    def get_interface_description(self) -> str:
        return """
        Event Bus Tool (event_bus):
        - PURPOSE: Orchestrate asynchronous communication between isolated domains.
        - IDEAL FOR: Side effects (notifications, logs) and cross-domain RPC requests.
        - CAPABILITIES:
            - publish(name, data): Fire and forget event. 
            - subscribe(name, callback): Listens for events. Callback receives {_event_name, payload}.
            - request(name, data, timeout=5): Synchronous Request-Response (RPC) over events.
        """

    def subscribe(self, event_name, callback):
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            self._subscribers[event_name].append(callback)

    def publish(self, event_name, data):
        with self._lock:
            # Capture current list to avoid concurrency issues when iterating
            callbacks = list(self._subscribers.get(event_name, []))
            # Add wildcard '*' subscribers
            callbacks += list(self._subscribers.get('*', []))
            
        # Enrich the payload with event metadata
        enriched_data = {
            "_event_name": event_name,
            "payload": data
        }

        # Track correlation
        event_id = str(uuid.uuid4())
        parent_id = getattr(self._local, 'current_event_id', None)

        # Record trace (ignore internal reply events to avoid noise)
        if not event_name.startswith("reply."):
            # 1. Detect Emitter magically using inspect stack
            emitter = "Unknown"
            try:
                # stack[0] is publish, stack[1] is the caller
                caller_frame = inspect.stack()[1][0]
                if 'self' in caller_frame.f_locals:
                    emitter = caller_frame.f_locals['self'].__class__.__name__
                else:
                    mod = inspect.getmodule(caller_frame)
                    if mod:
                        emitter = mod.__name__
            except Exception:
                pass

            # 2. Detect Subscribers
            subscriber_names = []
            for cb in callbacks:
                sub_name = "UnknownPlugin"
                if hasattr(cb, '__self__'):
                    sub_name = cb.__self__.__class__.__name__
                elif hasattr(cb, '__qualname__'):
                    sub_name = cb.__qualname__.split('.')[0]
                elif hasattr(cb, '__name__'):
                    sub_name = cb.__name__
                if sub_name not in subscriber_names:
                    subscriber_names.append(sub_name)

            self._tracer_log.append({
                "id": event_id,
                "parent_id": parent_id,
                "timestamp": time.time(),
                "event_name": event_name,
                "emitter": emitter,
                "subscribers": subscriber_names,
                "payload_keys": list(data.keys()) if isinstance(data, dict) else []
            })

        for callback in callbacks:
            def safe_callback_execution(cb, payload, eid):
                # Restore correlation context in the worker thread
                prev_eid = getattr(self._local, 'current_event_id', None)
                self._local.current_event_id = eid
                try:
                    cb(payload)
                except Exception as e:
                    print(f"[EventBus] Error in subscriber for {event_name}: {e}")
                finally:
                    self._local.current_event_id = prev_eid

            # Submit work to thread pool
            self._executor.submit(safe_callback_execution, callback, enriched_data, event_id)

    def shutdown(self):
        """Orderly shutdown of the thread pool"""
        print("[EventBus] Closing ThreadPool...")
        self._executor.shutdown(wait=False)

    def request(self, event_name, data, timeout=5):
        """
        Sends an event and waits for a response using a unique Correlation ID.
        """
        correlation_id = str(uuid.uuid4())
        reply_to = f"reply.{event_name}.{correlation_id[:8]}"
        
        # Inject control metadata
        data["_metadata"] = {
            "correlation_id": correlation_id,
            "reply_to": reply_to
        }

        response_container = {"data": None}
        event_ready = threading.Event()

        def response_handler(payload):
            meta = payload.get("_metadata", {})
            if meta.get("correlation_id") == correlation_id:
                response_container["data"] = payload
                event_ready.set()

        # Subscribe to temporary reply channel
        self.subscribe(reply_to, response_handler)

        try:
            # Launch the request
            self.publish(event_name, data)

            # Wait for the response
            if not event_ready.wait(timeout):
                raise TimeoutError(f"Timeout waiting for response from '{event_name}' ({timeout}s)")

            return response_container["data"]
        finally:
            # Cleanup: remove temporary subscriber
            with self._lock:
                if reply_to in self._subscribers:
                    self._subscribers[reply_to].remove(response_handler)
                    if not self._subscribers[reply_to]:
                        del self._subscribers[reply_to]