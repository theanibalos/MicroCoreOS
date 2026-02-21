from core.base_plugin import BasePlugin

class ObservabilityPlugin(BasePlugin):
    def __init__(self, http, registry, event_bus, logger):
        self.http = http
        self.registry = registry
        self.bus = event_bus
        self.logger = logger
        self._history = []
        self.MAX_HISTORY = 50

    def on_boot(self):
        """Registers the observability endpoint and subscribes to events"""
        self.http.add_endpoint(
            path="/obs/system", 
            method="GET", 
            handler=self.get_system_status,
            tags=["System"]
        )
        
        # Subscribe to ALL events for the Tracer
        self.bus.subscribe("*", self._trace_event)
        
        # Bridge logger to EventBus for full visibility
        self.logger.add_sink(self._bridge_log_to_bus)
        
        self.logger.info("Observability Plugin active at /obs/system. Event tracer enabled.")

    def _bridge_log_to_bus(self, level, message, timestamp):
        """Callback from LoggerTool. Forwards log events into the EventBus"""
        self.bus.publish("system.log", {
            "level": level,
            "message": message,
            "timestamp": timestamp
        })

    def _trace_event(self, data, event_name):
        """Captures events for the internal history buffer"""
        from datetime import datetime
        event_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            "payload": str(data)[:200]  # Truncate for safety
        }
        self._history.append(event_entry)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def execute(self, **kwargs):
        """Returns complex system status including event history"""
        dump = self.registry.get_system_dump()
        dump["events"] = self._history
        return dump

    def get_system_status(self, data: dict, context):
        """Handler for the HTTP endpoint"""
        return self.execute()
