from core.base_plugin import BasePlugin

class GetUserByIdPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/users/{user_id}", 
            "GET", 
            self.handler, 
            tags=["Users"]
        )

    async def handler(self, data: dict, context):
        return await self.execute(data)

    async def execute(self, data: dict):
        try:
            user_id = data.get("user_id")
            if not user_id:
                return {"success": False, "error": "Missing user_id"}

            # AWAIT DB query
            records = await self.db.query("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
            if not records:
                return {"success": False, "error": "User not found"}
            
            row = records[0]
            user = {"id": row[0], "name": row[1], "email": row[2]}
            return {"success": True, "data": user}
        except Exception as e:
            self.logger.error(f"Failed to fetch user {data.get('user_id')}: {e}")
            return {"success": False, "error": str(e)}
