from core.base_plugin import BasePlugin

class WelcomeServicePlugin(BasePlugin):
    """
    Consumer Plugin: Observes the 'user.created' event and performs
    a side-effect (simulating sending a welcome email).
    """
    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        # We subscribe to the event published by CreateUserPlugin
        await self.bus.subscribe("user.created", self.on_user_created)
        self.logger.info("[WelcomeService] Listening for new users...")

    async def on_user_created(self, data: dict, event_name: str):
        """
        Callback triggered by the EventBus when 'user.created' is published.
        """
        email = data.get("email")
        user_id = data.get("id")
        
        self.logger.info(f"✨ [WelcomeService] Sending welcome email to {email} (User ID: {user_id})")
        
        # This is a side-effect. If this fails, the 'monitoring callback' 
        # in the EventBus will catch the exception and log it, ensuring 
        # the main CreateUserPlugin isn't affected.
