from pydantic import BaseModel
from core.base_plugin import BasePlugin


# ── Consumed event, tolerant reader: ONLY the fields this plugin needs ────────
# (never import the publisher's payload model; extra keys are ignored)
class UserCreatedData(BaseModel):
    id: int
    email: str


# ── Event payload schema (publisher owns the contract) ───────────────────────
class WelcomeNotifySentPayload(BaseModel):
    user_id: int
    email: str


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
        user = UserCreatedData(**event.payload)
        self.logger.info(f"[WelcomeService] Sending welcome email to {user.email} (User ID: {user.id})")
        await self.bus.publish(
            "welcome.notify.sent",
            WelcomeNotifySentPayload(user_id=user.id, email=user.email).model_dump(),
        )
