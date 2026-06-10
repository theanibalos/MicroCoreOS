from core.base_plugin import BasePlugin


class WelcomeServicePlugin(BasePlugin):
    """
    Listens for 'user.created' events and performs side-effects like sending welcome emails.
    """

    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        await self.bus.subscribe("user.created", self.on_user_created)
        self.logger.info("[WelcomeService] Listening for new users...")

    async def on_user_created(self, event) -> None:
        """
        Processes a new user creation event.
        """
        data = event.payload
        email = data.get("email")
        user_id = data.get("id")
        self.logger.info(f"[WelcomeService] Sending welcome email to {email} (User ID: {user_id})")
        await self.bus.publish("welcome.notify.sent", {"user_id": user_id, "email": email})
