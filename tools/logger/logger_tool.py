from core.base_tool import BaseTool
import datetime

class LoggerTool(BaseTool):
    def __init__(self):
        self._event_bus = None

    @property
    def name(self) -> str:
        return "logger"

    def setup(self):
        """Inicialización del logger (en este caso, simple consola)"""
        print("[System] LoggerTool inicializado correctamente.")

    def on_boot_complete(self, container):
        """Obtenemos el event_bus para publicar logs como eventos observables."""
        if container.has_tool("event_bus"):
            self._event_bus = container.get("event_bus")
            print("[Logger] Conectado al EventBus para observabilidad.")

    def get_interface_description(self) -> str:
        """
        Este es el manual para la IA.
        """
        return """
        Herramienta de Logs:
        - info(message): Registra información general.
        - error(message): Registra errores críticos.
        - warning(message): Registra advertencias.
        Todos los logs se publican también al event_bus como 'system.log'.
        """

    def _publish_log(self, level: str, message: str):
        """Publica el log al event_bus si está disponible."""
        if self._event_bus:
            self._event_bus.publish("system.log", {
                "level": level,
                "message": message,
                "timestamp": datetime.datetime.now().isoformat()
            })

    # Métodos funcionales que usará el plugin
    def info(self, message: str):
        print(f"[{datetime.datetime.now()}] [INFO] {message}")
        self._publish_log("INFO", message)

    def error(self, message: str):
        print(f"[{datetime.datetime.now()}] [ERROR] {message}")
        self._publish_log("ERROR", message)

    def warning(self, message: str):
        print(f"[{datetime.datetime.now()}] [WARN] {message}")
        self._publish_log("WARN", message)