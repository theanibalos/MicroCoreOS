from core.base_plugin import BasePlugin

class GetUserByIdPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/users/{user_id}", "GET", self.execute, tags=["Users"])

    async def execute(self, data: dict, context=None):
        try:
            user_id = int(data.get("user_id"))
            if not user_id:
                return {"success": False, "error": "Missing user_id"}

            row = await self.db.query_one("SELECT id, name, email FROM users WHERE id = $1", [user_id])
            if not row:
                return {"success": False, "error": "User not found"}

            return {"success": True, "data": {"id": row["id"], "name": row["name"], "email": row["email"]}}
        except Exception as e:
            self.logger.error(f"Failed to fetch user {data.get('user_id')}: {e}")
            return {"success": False, "error": str(e)}
