from core.base_tool import BaseTool
from core.context import current_identity_var
import datetime
from typing import List, Callable

class LoggerTool(BaseTool):
    """
    Autonomous Logging Tool.
    Pure and isolated: No dependencies on other tools (like EventBus).
    Uses a Sink Pattern for external tools/plugins to observe logs.
    """
    def __init__(self):
        self._sinks: List[Callable[[str, str, str], None]] = []

    @property
    def name(self) -> str:
        return "logger"

    def setup(self):
        """Logger initialization."""
        print("[System] LoggerTool initialized successfully (Sink Pattern active).")

    def add_sink(self, callback: Callable[[str, str, str], None]):
        """
        Registers an external callback to receive all system logs.
        Allows plugins to bridge logs to EventBus or external APIs.
        """
        if callback not in self._sinks:
            self._sinks.append(callback)

    def get_interface_description(self) -> str:
        return """
        Logging Tool (logger):
        - PURPOSE: Record system events and business activity for audit and debugging.
        - CAPABILITIES:
            - info(message): General information.
            - error(message): Critical failures.
            - warning(message): Non-critical alerts.
            - add_sink(callback): Connect external observability (e.g. to EventBus).
                Sink signature: callback(level: str, message: str, timestamp: str, identity: str)
                'identity' is the current plugin/tool context (from current_identity_var).
                Use it to attribute errors to specific plugins for health tracking.
        """

    def _broadcast_to_sinks(self, level: str, message: str):
        """Sends the log to all registered observers."""
        timestamp = datetime.datetime.now().isoformat()
        identity = current_identity_var.get()
        for sink in self._sinks:
            try:
                sink(level, message, timestamp, identity)
            except Exception as e:
                # We use print here to avoid recursion if a sink fails
                print(f"[Logger] Sink Failure: {e}")

    def info(self, message: str):
        identity = current_identity_var.get()
        print(f"[{datetime.datetime.now()}] [INFO] [{identity}] {message}")
        self._broadcast_to_sinks("INFO", message)

    def error(self, message: str):
        identity = current_identity_var.get()
        print(f"[{datetime.datetime.now()}] [ERROR] [{identity}] {message}")
        self._broadcast_to_sinks("ERROR", message)

    def warning(self, message: str):
        identity = current_identity_var.get()
        print(f"[{datetime.datetime.now()}] [WARN] [{identity}] {message}")
        self._broadcast_to_sinks("WARN", message)