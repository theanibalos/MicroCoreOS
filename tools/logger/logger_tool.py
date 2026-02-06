from core.base_tool import BaseTool
import datetime

class LoggerTool(BaseTool):
    def __init__(self):
        self._event_bus = None

    @property
    def name(self) -> str:
        return "logger"

    def setup(self):
        """Logger initialization (simple console output)"""
        print("[System] LoggerTool initialized successfully.")

    def on_boot_complete(self, container):
        """Get the event_bus to publish logs as observable events."""
        if container.has_tool("event_bus"):
            self._event_bus = container.get("event_bus")
            print("[Logger] Connected to EventBus for observability.")

    def get_interface_description(self) -> str:
        """
        This is the manual for the AI.
        """
        return """
        Logging Tool:
        - info(message): Logs general information.
        - error(message): Logs critical errors.
        - warning(message): Logs warnings.
        All logs are also published to event_bus as 'system.log'.
        """

    def _publish_log(self, level: str, message: str):
        """Publishes the log to event_bus if available."""
        if self._event_bus:
            self._event_bus.publish("system.log", {
                "level": level,
                "message": message,
                "timestamp": datetime.datetime.now().isoformat()
            })

    # Functional methods that plugins will use
    def info(self, message: str):
        print(f"[{datetime.datetime.now()}] [INFO] {message}")
        self._publish_log("INFO", message)

    def error(self, message: str):
        print(f"[{datetime.datetime.now()}] [ERROR] {message}")
        self._publish_log("ERROR", message)

    def warning(self, message: str):
        print(f"[{datetime.datetime.now()}] [WARN] {message}")
        self._publish_log("WARN", message)