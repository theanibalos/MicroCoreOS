from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserIdRequest, UserResponse

class DeleteUserPlugin(BasePlugin):
    def __init__(self, http, db, logger, event_bus, identity):
        self.http = http
        self.db = db
        self.logger = logger
        self.bus = event_bus
        self.identity = identity

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/delete", 
            method="DELETE", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserIdRequest,
            response_model=UserResponse,
            security_guard=self.http.get_bearer_guard(self.identity.decode_token)
        )
        self.logger.info("DeleteUserPlugin: Endpoint /users/delete registered with Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")

        # --- SECURITY CHECK ---
        auth = data.get("_auth", {})
        requester_id = auth.get("user_id")

        if not requester_id:
            self.logger.warning(f"Unauthorized deletion attempt for user {user_id}")
            return {"success": False, "error": "Unauthorized"}

        if requester_id != user_id:
            self.logger.warning(f"User {requester_id} tried to delete user {user_id}")
            return {"success": False, "error": "Forbidden: You can only delete your own account."}
        # ----------------------

        try:
            # Check existence before deleting for better feedback
            row = self.db.query("SELECT id FROM users WHERE id = ?", (user_id,))
            if not row:
                return {"success": False, "error": "User not found"}

            self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.logger.warning(f"User {user_id} deleted.")
            
            # Notify the system
            self.bus.publish("users.deleted", {"id": user_id})
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error during deletion: {e}")
            return {"success": False, "error": str(e)}
