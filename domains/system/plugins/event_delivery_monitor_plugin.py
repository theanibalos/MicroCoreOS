import asyncio
from core.base_plugin import BasePlugin


class EventDeliveryMonitorPlugin(BasePlugin):
    """
    Monitors event delivery and alerts when a subscriber fails to process an event.

    Hooks into the EventBus failure sink (add_failure_listener) — called synchronously
    when a subscriber raises during dispatch. Publishes 'event.delivery.failed' so the
    failure is visible in the observability stream (/system/events/stream).

    No external infrastructure required. The plugin is the dead-letter mechanism.
    """

    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.bus.add_failure_listener(self._on_failure)
        self.logger.info("[EventDeliveryMonitor] Watching for subscriber failures.")

    def _on_failure(self, record: dict) -> None:
        """
        Called synchronously by EventBus when a subscriber raises.
        Schedules the alert as a fire-and-forget task to avoid blocking the bus.
        record = {event, event_id, subscriber, error}
        """
        asyncio.create_task(self._publish_alert(record))

    async def _publish_alert(self, record: dict) -> None:
        # Guard: never re-publish if the failing event was itself event.delivery.failed
        # (prevents infinite loop when a wildcard subscriber fails on every event)
        if record.get("event") == "event.delivery.failed":
            self.logger.error(
                f"[EventDeliveryMonitor] Recursive delivery failure suppressed — "
                f"subscriber='{record.get('subscriber')}' error='{record.get('error')}'"
            )
            return
        self.logger.error(
            f"[EventDeliveryMonitor] Delivery failure — "
            f"event='{record['event']}' subscriber='{record['subscriber']}' error='{record['error']}'"
        )
        await self.bus.publish("event.delivery.failed", record)
