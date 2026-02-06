# micro_core_os/create_user_plugin.py
# MicroCoreOS Implementation: Single-file Feature (Plugin)

from core.base_plugin import BasePlugin
from pydantic import BaseModel, EmailStr

# --- DTOs (Co-located with behavior) ---

class CreateUserDTO(BaseModel):
    name: str
    email: EmailStr

class UserResponse(BaseModel):
    success: bool
    user_id: int | None = None
    error: str | None = None


class CreateUserPlugin(BasePlugin):
    """
    Plugin: CreateUser.
    Encapsulates route, validation, and persistence in ONE file.
    """
    def __init__(self, http_server, db, logger):
        self.http = http_server
        self.db = db
        self.logger = logger

    def on_boot(self):
        # Port/Adapter logic is handled by the Kernel via Tool Injection
        self.http.add_endpoint(
            path="/users/create",
            method="POST",
            handler=self.execute,
            request_model=CreateUserDTO,
            response_model=UserResponse
        )

    def execute(self, data: dict):
        # 1. Validation (Business Rules)
        if not "@" in data["email"]:
            return {"success": False, "error": "Invalid email"}

        try:
            # 2. Persistence (Infrastructure through Tool)
            user_id = self.db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                (data["name"], data["email"])
            )
            
            self.logger.info(f"User {data['name']} created.")
            return {"success": True, "user_id": user_id}

        except Exception as e:
            return {"success": False, "error": str(e)}
