from typing import TYPE_CHECKING
from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserCreate, UserResponse

if TYPE_CHECKING:
    from tools.http_server.http_server_tool import HttpServerTool
    from tools.sqlite.sqlite_tool import SqliteTool
    from tools.logger.logger_tool import LoggerTool
    from tools.event_bus.event_bus_tool import EventBusTool

class CreateUserPlugin(BasePlugin):
    def __init__(self, 
        http: 'HttpServerTool', 
        identity: 'IdentityTool',
        db: 'SqliteTool', 
        logger: 'LoggerTool', 
        event_bus: 'EventBusTool'
    ):
        self.http = http
        self.identity = identity
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        # Register with Schema support
        self.http.add_endpoint(
            path="/users/create", 
            method="POST", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserCreate,
            response_model=UserResponse
        )
        self.logger.info("CreateUserPlugin: Endpoint /users/create registered.")

    def execute(self, data: dict):
        name = data.get("name")
        email = data.get("email")
        password = data.get("password")

        try:
            # 1. Hashing (Using dedicated identity tool)
            password_hash = self.identity.hash_password(password)

            # 2. Insert into database
            user_id = self.db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)", 
                (name, email, password_hash)
            )
            
            user = UserModel(id=user_id, name=name, email=email, password_hash=password_hash)
            self.logger.info(f"User {name} created with ID {user_id}.")
            
            # Notify the system
            self.bus.publish("users.created", user.to_dict())
            
            # Return public data (remove hash for response if necessary, but UserModel.to_dict includes it)
            # Actually, UserResponse uses UserPublic which DOES NOT include password_hash
            return {"success": True, "user": user.to_dict()}
            
        except Exception as e:
            error_msg = str(e)
            user_msg = "An internal error occurred."

            if "UNIQUE constraint failed" in error_msg:
                user_msg = "Email is already registered."
                self.logger.warning(f"CreateUserPlugin: Attempt to register duplicate email: {email}")
            else:
                self.logger.error(f"CreateUserPlugin: Internal error: {error_msg}")

            return {"success": False, "error": user_msg}
