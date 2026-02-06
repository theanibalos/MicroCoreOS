import asyncio
import json
from core.base_plugin import BasePlugin

class RealTimeBridgePlugin(BasePlugin):
    """
    Bridge between the internal EventBus and WebSocket clients.
    Listens to ALL events (*) and relays them to active connections.
    """
    def __init__(self, http_server, event_bus, logger):
        self.http = http_server
        self.bus = event_bus
        self.logger = logger
        self._clients = []  # List of active websockets
        self._lock = asyncio.Lock()
        self._loop = None   # FastAPI's loop (captured when first client connects)

    def on_boot(self):
        # 1. Register WebSocket endpoint
        self.http.add_ws_endpoint("/ws/events", self._handle_ws_connect)
        
        # 2. Subscribe to ALL system events
        self.bus.subscribe("*", self._on_system_event)
        
        self.logger.info("RealTimeBridgePlugin: WebSocket active at /ws/events. Listening to all events.")

    async def _handle_ws_connect(self, websocket):
        """Handles new WebSocket connections."""
        # Capture the loop from the first connection (which is FastAPI's loop)
        if not self._loop:
            self._loop = asyncio.get_event_loop()

        async with self._lock:
            self._clients.append(websocket)
        
        self.logger.info(f"[WS] Client connected. Total: {len(self._clients)}")
        
        try:
            # Keep the connection open receiving messages (ping/pong)
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            async with self._lock:
                if websocket in self._clients:
                    self._clients.remove(websocket)
            self.logger.info(f"[WS] Client disconnected. Total: {len(self._clients)}")

    def _on_system_event(self, enriched_data):
        """Callback when any event occurs in the system."""
        event_name = enriched_data.get("_event_name", "unknown")
        payload = enriched_data.get("payload", {})
        
        # Prepare JSON message for the frontend
        message = json.dumps({
            "type": "event",
            "event": event_name,
            "data": self._serialize_payload(payload)
        })
        
        # Send to all connected clients
        self._broadcast(message)

    def _serialize_payload(self, payload):
        """Tries to serialize the payload, handles non-JSON objects."""
        try:
            json.dumps(payload)
            return payload
        except (TypeError, ValueError):
            return str(payload)

    def _broadcast(self, message: str):
        """Sends a message to all WebSocket clients."""
        if not self._clients or not self._loop:
            return

        # Helper function for async sending
        async def send_to_client(client, msg):
            try:
                await client.send_text(msg)
            except Exception:
                pass

        # Send safely from EventBus thread to FastAPI's loop
        for client in list(self._clients):
            asyncio.run_coroutine_threadsafe(send_to_client(client, message), self._loop)

    def execute(self, **kwargs):
        return {
            "success": True, 
            "active_clients": len(self._clients),
            "loop_active": self._loop is not None,
            "message": "RealTimeBridge is forwarding events to WebSocket clients."
        }
