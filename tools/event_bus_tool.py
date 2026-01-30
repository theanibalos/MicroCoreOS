from core.base_tool import BaseTool

class EventBusTool(BaseTool):
    def __init__(self):
        self._subscribers = {}

    @property
    def name(self) -> str:
        return "event_bus"

    def setup(self):
        print("[System] EventBusTool: Listo para orquestar eventos.")

    def get_interface_description(self) -> str:
        return "Permite publicar eventos con .publish(nombre, datos) y suscribirse con .subscribe(nombre, callback)."

    def subscribe(self, event_name, callback):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    def publish(self, event_name, data):
        if event_name in self._subscribers:
            for callback in self._subscribers[event_name]:
                callback(data)