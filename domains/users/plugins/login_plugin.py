from typing import TYPE_CHECKING
from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserLogin, TokenResponse

if TYPE_CHECKING:
    from tools.http_server.http_server_tool import HttpServerTool
    from tools.sqlite.sqlite_tool import SqliteTool
    from tools.logger.logger_tool import LoggerTool

class LoginPlugin(BasePlugin):
    def __init__(self, 
        http: 'HttpServerTool', 
        identity: 'IdentityTool',
        db: 'SqliteTool', 
        logger: 'LoggerTool'
    ):
        self.http = http
        self.identity = identity
        self.db = db
        self.logger = logger

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/login", 
            method="POST", 
            handler=self.execute, 
            tags=["Auth"],
            request_model=UserLogin,
            response_model=TokenResponse
        )
        self.logger.info("LoginPlugin: Endpoint /users/login registered.")

    def execute(self, data: dict):
        email = data.get("email")
        password = data.get("password")

        try:
            # 1. Fetch user by email
            rows = self.db.query(
                "SELECT id, name, email, password_hash FROM users WHERE email = ?", 
                (email,)
            )
            
            if not rows:
                return {"success": False, "error": "Invalid email or password."}
            
            row = rows[0]
            user = UserModel.from_row(row)

            # 2. Verify password (Using identity tool)
            if not self.identity.verify_password(password, user.password_hash):
                return {"success": False, "error": "Invalid email or password."}

            # 3. Generate token (Using identity tool)
            token = self.identity.generate_token({"user_id": user.id})
            
            self.logger.info(f"User {email} logged in successfully.")
            return {"success": True, "token": token}
            
        except Exception as e:
            self.logger.error(f"Error during login: {e}")
            return {"success": False, "error": str(e)}
