from core.base_plugin import BasePlugin

class GetMePlugin(BasePlugin):
    def __init__(self, http, db, auth, logger):
        self.http = http
        self.db = db
        self.auth = auth
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/users/me",
            method="GET",
            handler=self.handler,
            tags=["Users"],
            auth_validator=self._validate_token
        )

    async def _validate_token(self, token: str):
        try:
            # AuthTool is sync, but we treat it as callable from here
            return self.auth.decode_token(token)
        except Exception:
            return None

    async def handler(self, data: dict, context):
        return await self.execute(data)

    async def execute(self, data: dict):
        try:
            # The http tool injects the payload into '_auth' if validation passes
            auth_payload = data.get("_auth")
            if not auth_payload:
                return {"success": False, "error": "Unauthorized"}
            
            user_id = auth_payload.get("sub")
            
            # AWAIT Database call
            records = await self.db.query("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
            if not records:
                return {"success": False, "error": "User no longer exists"}
            
            id, name, email = records[0]
            return {
                "success": True, 
                "data": {
                    "id": id,
                    "name": name,
                    "email": email
                }
            }
        except Exception as e:
            self.logger.error(f"Error in /users/me: {e}")
            return {"success": False, "error": str(e)}
