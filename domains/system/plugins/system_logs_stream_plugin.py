import asyncio
import json
from core.base_plugin import BasePlugin


class SystemLogsStreamPlugin(BasePlugin):
    """
    Streams every log entry in real time to connected WebSocket clients.
    Connect to ws://<host>/system/logs/stream to receive live log records.
    """

    def __init__(self, http, logger):
        self.http = http
        self.logger = logger
        self._clients: set = set()

    async def on_boot(self):
        self.logger.add_sink(self._on_log)
        self.http.add_ws_endpoint(
            "/system/logs/stream",
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )

    def _on_log(self, level: str, message: str, timestamp: str, identity: str):
        """Called synchronously by the logger on every log entry."""
        if not self._clients:
            return
        record = {"level": level, "message": message, "timestamp": timestamp, "identity": identity}
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
                await ws.receive_text()
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    async def _on_disconnect(self, ws):
        self._clients.discard(ws)
