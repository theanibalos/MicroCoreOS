from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserCreate, UserResponse

class CreateUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
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
        self.logger.info("CreateUserPlugin: Endpoint /users/create registered with Schema.")

    def execute(self, data: dict):
        name = data.get("name")
        email = data.get("email")

        try:
            # Insert into database
            user_id = self.db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", 
                (name, email)
            )
            
            user = UserModel(id=user_id, name=name, email=email)
            self.logger.info(f"User {name} created with ID {user_id}.")
            
            # Notify the system
            self.bus.publish("users.created", user.to_dict())
            
            return {"success": True, "user": user.to_dict()}
        except Exception as e:
            error_msg = str(e)
            if "UNIQUE constraint failed" in error_msg:
                error_msg = "Email is already registered."
                
            self.logger.error(f"Error creating user: {error_msg}")
            return {"success": False, "error": error_msg}
