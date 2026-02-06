import threading
import time
from core.base_plugin import BasePlugin

class HealthPlugin(BasePlugin):
    """
    Independent plugin responsible for monitoring the health of all system components.
    It periodically audits the Registry and emits health events.
    """
    def __init__(self, registry, event_bus, logger):
        self.registry = registry
        self.bus = event_bus
        self.logger = logger
        self._stop_event = threading.Event()
        self._monitor_thread = None
        self.CHECK_INTERVAL = 30 # seconds

    def on_boot(self):
        """Starts the health monitoring loop in a background thread"""
        self._monitor_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._monitor_thread.start()
        self.logger.info("HealthPlugin: Active and monitoring system components.")

    def _health_loop(self):
        """Background loop that periodically audits the system"""
        while not self._stop_event.is_set():
            try:
                system_state = self.registry.get_system_dump()
                tools = system_state.get("tools", {})
                plugins = system_state.get("plugins", {})

                # Perform basic audit
                stats = {
                    "total_tools": len(tools),
                    "total_plugins": len(plugins),
                    "failing_tools": [name for name, info in tools.items() if info.get("status") != "OK"],
                    "failing_plugins": [name for name, info in plugins.items() if info.get("status") not in ["READY", "RUNNING", "OK"]]
                }

                health_status = "HEALTHY" if not stats["failing_tools"] and not stats["failing_plugins"] else "DEGRADED"

                # Emit health event
                self.bus.publish("system.health_status", {
                    "status": health_status,
                    "stats": stats,
                    "timestamp": time.time()
                })

                if health_status == "DEGRADED":
                    self.logger.warning(f"System Health DEGRADED: {stats['failing_tools']} / {stats['failing_plugins']}")

            except Exception as e:
                self.logger.error(f"HealthPlugin: Error in audit loop: {e}")

            time.sleep(self.CHECK_INTERVAL)

    def shutdown(self):
        """Cleanly stops the monitoring thread"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        self.logger.info("HealthPlugin: Shutdown complete.")

    def execute(self, **kwargs):
        """Returns the latest audit summary"""
        system_state = self.registry.get_system_dump()
        return {
            "success": True,
            "audit": {
                "tools": system_state.get("tools"),
                "plugins": system_state.get("plugins")
            }
        }
