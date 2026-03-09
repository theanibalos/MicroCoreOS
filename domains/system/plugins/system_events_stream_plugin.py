import asyncio
import json
from core.base_plugin import BasePlugin


class SystemEventsStreamPlugin(BasePlugin):
    """
    Streams every event bus event in real time to connected WebSocket clients.
    Connect to ws://<host>/system/events/stream to receive live event records.
    """

    def __init__(self, http, event_bus):
        self.http = http
        self.event_bus = event_bus
        self._clients: set = set()

    async def on_boot(self):
        self.event_bus.add_listener(self._on_event)
        self.http.add_ws_endpoint(
            "/system/events/stream",
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )

    def _on_event(self, record: dict):
        """Called synchronously by the event bus on every event. Schedules async broadcast."""
        if not self._clients:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._broadcast(record))
            )
        except RuntimeError:
            pass

    async def _broadcast(self, record: dict):
        dead = set()
        message = json.dumps(record)
        for ws in self._clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _on_connect(self, ws):
        self._clients.add(ws)
        try:
            while True:
                await ws.receive_text()  # keep connection alive, ignore client messages
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    async def _on_disconnect(self, ws):
        self._clients.discard(ws)
