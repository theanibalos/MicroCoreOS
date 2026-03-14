from core.base_plugin import BasePlugin


class WelcomeServicePlugin(BasePlugin):
    """
    Event-driven plugin: listens for 'user.created' and performs side-effects.
    Demonstrates the pure event subscriber pattern — no HTTP endpoint needed.
    """

    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        await self.bus.subscribe("user.created", self.on_user_created)
        self.logger.info("[WelcomeService] Listening for new users...")

    async def on_user_created(self, data: dict) -> None:
        """
        Triggered by EventBus when 'user.created' is published.
        The bus calls this with a single argument: data dict.
        """
        email = data.get("email")
        user_id = data.get("id")
        self.logger.info(f"[WelcomeService] Sending welcome email to {email} (User ID: {user_id})")
        await self.bus.publish("welcome.notify.sent", {"user_id": user_id, "email": email})
