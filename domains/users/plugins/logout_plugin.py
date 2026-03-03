from typing import Optional
from pydantic import BaseModel
from core.base_plugin import BasePlugin


# ── Response schema ──────────────────────────────────────────────────────────
class LogoutResponse(BaseModel):
    success: bool
    data: None = None
    error: Optional[str] = None


class LogoutPlugin(BasePlugin):
    def __init__(self, http, logger):
        self.http = http
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(path="/auth/logout", method="POST", handler=self.execute,
                               tags=["Auth"], response_model=LogoutResponse)

    async def execute(self, data: dict, context=None) -> dict:
        if context:
            context.set_cookie("access_token", "", max_age=0)
        self.logger.info("User logged out successfully")
        return {"success": True}
