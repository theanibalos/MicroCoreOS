from core.base_plugin import BasePlugin
from domains.users.models.auth import LoginRequest, LoginResponse

class LoginPlugin(BasePlugin):
    def __init__(self, http, db, auth, logger):
        self.http = http
        self.db = db
        self.auth = auth
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            path="/auth/login",
            method="POST",
            handler=self.handler,
            tags=["Auth"],
            request_model=LoginRequest,
            response_model=LoginResponse
        )

    async def handler(self, data: dict, context):
        return await self.execute(data, context)

    async def execute(self, data: dict, context=None):
        try:
            # Validate input
            req = LoginRequest(**data)
            
            # Find user by email (AWAIT DB)
            records = await self.db.query(
                "SELECT id, password_hash FROM users WHERE email = ?",
                (req.email,)
            )
            
            if not records:
                return {"success": False, "error": "Invalid email or password"}
                
            user_id, hashed_password = records[0]
            
            if not hashed_password:
                 return {"success": False, "error": "User has no password set"}

            # Verify password (AuthTool is sync)
            if not self.auth.verify_password(req.password, hashed_password):
                return {"success": False, "error": "Invalid email or password"}
            
            # Create token
            token = self.auth.create_token({"sub": str(user_id), "email": req.email})
            
            # Set cookie for browser/Swagger automatic usage
            if context:
                context.set_cookie("access_token", token, max_age=86400) # 1 day
            
            self.logger.info(f"User {req.email} logged in successfully")
            return {"success": True, "token": token}
            
        except Exception as e:
            self.logger.error(f"Login error: {e}")
            return {"success": False, "error": str(e)}
