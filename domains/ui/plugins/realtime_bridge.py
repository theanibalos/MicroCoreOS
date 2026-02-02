import asyncio
import json
from core.base_plugin import BasePlugin

class RealTimeBridgePlugin(BasePlugin):
    """
    Puente entre el EventBus interno y los clientes WebSocket.
    Escucha TODOS los eventos (*) y los retransmite a las conexiones activas.
    """
    def __init__(self, http_server, event_bus, logger):
        self.http = http_server
        self.bus = event_bus
        self.logger = logger
        self._clients = []  # Lista de websockets activos
        self._lock = asyncio.Lock()
        self._loop = None   # Loop de FastAPI (se captura al conectar el primer cliente)

    def on_boot(self):
        # 1. Registrar endpoint WebSocket
        self.http.add_ws_endpoint("/ws/events", self._handle_ws_connect)
        
        # 2. Suscribirse a TODOS los eventos del sistema
        self.bus.subscribe("*", self._on_system_event)
        
        self.logger.info("RealTimeBridgePlugin: WebSocket activo en /ws/events. Escuchando todos los eventos.")

    async def _handle_ws_connect(self, websocket):
        """Maneja nuevas conexiones WebSocket."""
        # Capturamos el loop de la primera conexión (que es el loop de FastAPI)
        if not self._loop:
            self._loop = asyncio.get_event_loop()

        async with self._lock:
            self._clients.append(websocket)
        
        self.logger.info(f"[WS] Cliente conectado. Total: {len(self._clients)}")
        
        try:
            # Mantenemos la conexión abierta recibiendo mensajes (ping/pong)
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            async with self._lock:
                if websocket in self._clients:
                    self._clients.remove(websocket)
            self.logger.info(f"[WS] Cliente desconectado. Total: {len(self._clients)}")

    def _on_system_event(self, enriched_data):
        """Callback cuando cualquier evento ocurre en el sistema."""
        event_name = enriched_data.get("_event_name", "unknown")
        payload = enriched_data.get("payload", {})
        
        # Preparamos el mensaje JSON para el frontend
        message = json.dumps({
            "type": "event",
            "event": event_name,
            "data": self._serialize_payload(payload)
        })
        
        # Enviamos a todos los clientes conectados
        self._broadcast(message)

    def _serialize_payload(self, payload):
        """Intenta serializar el payload, maneja objetos no JSON."""
        try:
            json.dumps(payload)
            return payload
        except (TypeError, ValueError):
            return str(payload)

    def _broadcast(self, message: str):
        """Envía un mensaje a todos los clientes WebSocket."""
        if not self._clients or not self._loop:
            return

        # Función auxiliar para enviar de forma asíncrona
        async def send_to_client(client, msg):
            try:
                await client.send_text(msg)
            except Exception:
                pass

        # Enviamos de forma segura desde el hilo de EventBus al loop de FastAPI
        for client in list(self._clients):
            asyncio.run_coroutine_threadsafe(send_to_client(client, message), self._loop)

    def execute(self, **kwargs):
        return {
            "success": True, 
            "active_clients": len(self._clients),
            "loop_active": self._loop is not None,
            "message": "RealTimeBridge is forwarding events to WebSocket clients."
        }
