from core.base_plugin import BasePlugin

class WelcomeLogger(BasePlugin):
    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    def on_boot(self):
        # Subscribe to the event as soon as the system starts
        self.bus.subscribe("users.created", self.on_user_created)
        print("[Notifications] Subscribed to user events.")

    def on_user_created(self, data):
        # This function is executed automatically when another plugin publishes
        self.logger.info(f"--- EVENT RECEIVED ---")
        self.logger.info(f"Sending welcome email to {data['payload']['name']} ({data['payload']['email']})")

    def execute(self, data: dict, context=None):
        # Este plugin no se llama manualmente, vive de eventos.
        pass