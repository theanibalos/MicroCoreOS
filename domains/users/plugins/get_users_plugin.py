from core.base_plugin import BasePlugin

class GetUsersPlugin(BasePlugin):
    def __init__(self, http, db, logger):
        self.http = http
        self.db = db
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/users", 
            "GET", 
            self.handler, 
            tags=["Users"]
        )

    async def handler(self, data: dict, context):
        return await self.execute()

    async def execute(self):
        try:
            # AWAIT DB query
            records = await self.db.query("SELECT id, name, email FROM users")
            users = [{"id": row[0], "name": row[1], "email": row[2]} for row in records]
            return {"success": True, "data": users}
        except Exception as e:
            self.logger.error(f"Failed to fetch users: {e}")
            return {"success": False, "error": str(e)}
