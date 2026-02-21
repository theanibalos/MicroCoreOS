from typing import TYPE_CHECKING
from core.base_plugin import BasePlugin
import time

if TYPE_CHECKING:
    from tools.event_bus.event_bus_tool import EventBusTool
    from tools.logger.logger_tool import LoggerTool

class WelcomeEmailPlugin(BasePlugin):
    """
    Subscribes to 'users.created' and simulates sending a welcome email.
    Follows strict MicroCoreOS Event-Driven architecture.
    """
    def __init__(self, logger: 'LoggerTool', event_bus: 'EventBusTool'):
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        # 1. Routing / Subscriptions ONLY
        self.bus.subscribe("users.created", self.execute)
        self.logger.info("WelcomeEmailPlugin: Default event 'users.created' subscribed.")

    def execute(self, data: dict, event_name: str):
        # data arrives CLEAN — directly what was published
        user_name = data.get("name", "Unknown User")
        user_email = data.get("email", "unknown@example.com")
        
        self.logger.info(f"WelcomeEmailPlugin: Preparing to send welcome email to {user_name} ({user_email})...")
        time.sleep(1.5) # Simulate SMTP delay
        self.logger.info(f"WelcomeEmailPlugin: ✅ Email successfully sent to {user_email}.")

        # 2. State Change -> Event Publish
        event_payload = {
            "email_type": "welcome",
            "recipient": user_email,
            "status": "sent"
        }
        self.bus.publish("email.sent", event_payload)
