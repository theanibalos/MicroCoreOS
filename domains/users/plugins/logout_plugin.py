from core.base_plugin import BasePlugin

class LogoutPlugin(BasePlugin):
    def __init__(self, http, logger):
        self.http = http
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/auth/logout",
            method="POST",
            handler=self.handler,
            tags=["Auth"]
        )

    async def handler(self, data: dict, context):
        return await self.execute(context)

    async def execute(self, context):
        try:
            if context:
                context.set_cookie("access_token", "", max_age=0)
            
            self.logger.info("User logged out successfully")
            return {"success": True, "message": "Successfully logged out"}
        except Exception as e:
            self.logger.error(f"Logout error: {e}")
            return {"success": False, "error": str(e)}
