from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserResponse

class GetMePlugin(BasePlugin):
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
        # PROTECTED ROUTE:
        # 1. We ask the HttpTool to build a 'Bearer Guard'.
        # 2. we provide the pure IdentityTool decoding logic as a callback.
        # This keeps tools isolated and decoupled.
        self.http.add_endpoint(
            path="/users/me", 
            method="GET", 
            handler=self.execute, 
            tags=["Users"],
            response_model=UserResponse,
            security_guard=self.http.get_bearer_guard(self.identity.decode_token)
        )
        self.logger.info("GetMePlugin: Protected endpoint /users/me registered.")

    def execute(self, data: dict):
        # Injected by the HttpServerTool Guard as '_auth' (infrastructure key)
        auth_payload = data.get("_auth", {})
        user_id = auth_payload.get("user_id") # Domain-specific key extracted here
        
        if not user_id:
            return {"success": False, "error": "Unauthorized: Missing identity in request"}

        # Use all 4 columns for UserModel.from_row
        row = self.db.query("SELECT id, name, email, password_hash FROM users WHERE id = ?", (user_id,))
        if not row: 
            return {"success": False, "error": "User not found"}
        
        user = UserModel.from_row(row[0])
        return {"success": True, "user": user.to_dict()}
