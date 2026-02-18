from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserUpdateWithId, UserResponse

class UpdateUserPlugin(BasePlugin):
    """
    Plugin for updating existing users.
    - Saves changes to database
    - Publishes users.updated event
    - Logs operations
    """
    
    def __init__(self, http, db, logger, event_bus, identity):
        self.http = http
        self.db = db
        self.logger = logger
        self.bus = event_bus
        self.identity = identity

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/update", 
            method="PUT", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserUpdateWithId,
            response_model=UserResponse,
            security_guard=self.http.get_bearer_guard(self.identity.decode_token)
        )
        self.logger.info("UpdateUserPlugin: Endpoint /users/update registered with Schema.")

    def execute(self, data: dict):
        # 0. Security: Verify Authentication and Authorization
        auth_payload = data.get("_auth", {})
        auth_user_id = auth_payload.get("user_id")

        if not auth_user_id:
             return {"success": False, "error": "Unauthorized: Missing identity."}

        target_user_id = data.get("id")

        if auth_user_id != target_user_id:
             self.logger.warning(f"UpdateUserPlugin: Unauthorized update attempt by User {auth_user_id} on User {target_user_id}")
             return {"success": False, "error": "Forbidden: You can only update your own profile."}

        user_id = target_user_id
        name = data.get("name")
        email = data.get("email")

        # 1. Validate: Check that user exists
        try:
            existing = self.db.query(
                "SELECT id, name, email, password_hash FROM users WHERE id = ?", 
                (user_id,)
            )
            if not existing:
                self.logger.warning(f"UpdateUserPlugin: User with ID {user_id} not found.")
                return {"success": False, "error": f"User with ID {user_id} does not exist."}
            
            current_user = UserModel.from_row(existing[0])
        except Exception as e:
            self.logger.error(f"UpdateUserPlugin: Error querying user: {e}")
            return {"success": False, "error": str(e)}

        # 2. Validate fields if provided
        if name is not None:
            valid, error = UserModel.validate_name(name)
            if not valid:
                self.logger.warning(f"UpdateUserPlugin: Name validation failed: {error}")
                return {"success": False, "error": f"Invalid name: {error}"}
        
        if email is not None:
            valid, error = UserModel.validate_email(email)
            if not valid:
                self.logger.warning(f"UpdateUserPlugin: Email validation failed: {error}")
                return {"success": False, "error": f"Invalid email: {error}"}

        # 3. Process: Build dynamic query only with provided fields
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if email is not None:
            updates.append("email = ?")
            params.append(email)
        
        if not updates:
            self.logger.warning("UpdateUserPlugin: No fields provided for update.")
            return {"success": False, "error": "No fields provided for update."}
        
        params.append(user_id)
        
        # 4. Act: Execute update on database
        try:
            self.db.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            
            # Get updated user
            updated_row = self.db.query(
                "SELECT id, name, email, password_hash FROM users WHERE id = ?", 
                (user_id,)
            )
            updated_user = UserModel.from_row(updated_row[0])
            
            self.logger.info(f"UpdateUserPlugin: User {user_id} updated successfully.")
            
            # Publish event to the system
            self.bus.publish("users.updated", {
                "user_id": user_id,
                "changes": {
                    "name": name if name is not None else current_user.name,
                    "email": email if email is not None else current_user.email
                },
                "previous": current_user.to_dict()
            })
            
            # 5. Respond
            return {"success": True, "user": updated_user.to_dict()}
            
        except Exception as e:
            error_msg = str(e)
            if "UNIQUE constraint failed" in error_msg:
                error_msg = "Email is already in use by another user."
            
            self.logger.error(f"UpdateUserPlugin: Error updating user: {error_msg}")
            return {"success": False, "error": error_msg}
