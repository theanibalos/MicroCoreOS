import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from core.base_tool import BaseTool

class EventBusTool(BaseTool):
    def __init__(self):
        self._subscribers = {}
        self._lock = threading.Lock()
        # Creamos un pool de hilos para procesar eventos sin saturar el sistema
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="BusWorker")

    @property
    def name(self) -> str:
        return "event_bus"

    def setup(self):
        print("[System] EventBusTool: Listo para orquestar eventos con ThreadPool (max=10).")

    def get_interface_description(self) -> str:
        return """
        Permite comunicación entre plugins:
        - publish(nombre, datos): Dispara y olvida.
        - subscribe(nombre, callback): Escucha eventos. Usa '*' para escuchar TODOS.
        - request(nombre, datos, timeout=5): Envía y espera respuesta (RPC).
        """

    def subscribe(self, event_name, callback):
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            self._subscribers[event_name].append(callback)

    def publish(self, event_name, data):
        with self._lock:
            # Capturamos la lista actual para evitar problemas de concurrencia al iterar
            callbacks = list(self._subscribers.get(event_name, []))
            # Añadimos los suscriptores con wildcard '*'
            callbacks += list(self._subscribers.get('*', []))
        
        # Enriquecemos el payload con metadatos del evento
        enriched_data = {
            "_event_name": event_name,
            "payload": data
        }

        for callback in callbacks:
            def safe_callback_execution(cb, payload):
                try:
                    cb(payload)
                except Exception as e:
                    print(f"[EventBus] Error en suscriptor de {event_name}: {e}")

            # Enviamos el trabajo al pool de hilos en lugar de crear un hilo nuevo cada vez
            self._executor.submit(safe_callback_execution, callback, enriched_data)

    def shutdown(self):
        """Cierre ordenado del pool de hilos"""
        print("[EventBus] Cerrando ThreadPool...")
        self._executor.shutdown(wait=False)

    def request(self, event_name, data, timeout=5):
        """
        Envía un evento y espera una respuesta usando un Correlation ID único.
        """
        correlation_id = str(uuid.uuid4())
        reply_to = f"reply.{event_name}.{correlation_id[:8]}"
        
        # Inyectamos metadatos de control
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

        # Nos suscribimos al canal de respuesta temporal
        self.subscribe(reply_to, response_handler)

        try:
            # Lanzamos la petición
            self.publish(event_name, data)

            # Esperamos la respuesta
            if not event_ready.wait(timeout):
                raise TimeoutError(f"Timeout esperando respuesta de '{event_name}' ({timeout}s)")

            return response_container["data"]
        finally:
            # Limpieza: eliminamos el suscriptor temporal
            with self._lock:
                if reply_to in self._subscribers:
                    self._subscribers[reply_to].remove(response_handler)
                    if not self._subscribers[reply_to]:
                        del self._subscribers[reply_to]