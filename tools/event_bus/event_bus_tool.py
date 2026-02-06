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

    @property
    def name(self) -> str:
        return "event_bus"

    def setup(self):
        print("[System] EventBusTool: Ready to orchestrate events with ThreadPool (max=10).")

    def get_interface_description(self) -> str:
        return """
        Enables communication between plugins:
        - publish(name, data): Fire and forget.
        - subscribe(name, callback): Listen to events. Use '*' to listen to ALL.
        - request(name, data, timeout=5): Send and wait for response (RPC).
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

        for callback in callbacks:
            def safe_callback_execution(cb, payload):
                try:
                    cb(payload)
                except Exception as e:
                    print(f"[EventBus] Error in subscriber for {event_name}: {e}")

            # Submit work to thread pool instead of creating a new thread each time
            self._executor.submit(safe_callback_execution, callback, enriched_data)

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