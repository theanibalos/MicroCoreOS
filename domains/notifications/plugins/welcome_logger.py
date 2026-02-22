from core.base_plugin import BasePlugin

class WelcomeLogger(BasePlugin):
    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    def on_boot(self):
        # Subscribe to the event as soon as the system starts
        self.bus.subscribe("users.created", self.on_user_created)
        print("[Notifications] Subscribed to user events.")

    def on_user_created(self, data, event_name):
        # data arrives CLEAN — directly what was published
        self.logger.info(f"--- EVENT RECEIVED ---")
        self.logger.info(f"Sending welcome email to {data['name']} ({data['email']})")