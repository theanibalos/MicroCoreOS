from core.base_plugin import BasePlugin

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/users/{user_id}", "DELETE", self.execute, tags=["Users"])

    async def execute(self, data: dict, context=None):
        try:
            user_id = int(data.get("user_id"))
            if not user_id:
                return {"success": False, "error": "Missing user_id"}

            affected = await self.db.execute("DELETE FROM users WHERE id = $1", [user_id])
            if affected == 0:
                return {"success": False, "error": "User not found"}
            self.logger.info(f"User {user_id} deleted")

            await self.bus.publish("user.deleted", {"id": user_id})

            return {"success": True, "message": f"User {user_id} deleted successfully"}
        except Exception as e:
            self.logger.error(f"Failed to delete user: {e}")
            return {"success": False, "error": str(e)}
