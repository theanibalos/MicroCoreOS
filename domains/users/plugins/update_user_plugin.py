from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserUpdateWithId, UserResponse

class UpdateUserPlugin(BasePlugin):
    """
    Plugin for updating existing users.
    - Saves changes to database
    - Publishes users.updated event
    - Logs operations
    """
    
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint(
            path="/users/update", 
            method="PUT", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserUpdateWithId,
            response_model=UserResponse
        )
        self.logger.info("UpdateUserPlugin: Endpoint /users/update registered with Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")
        name = data.get("name")
        email = data.get("email")

        # 1. Validate: Check that user exists
        try:
            existing = self.db.query(
                "SELECT id, name, email FROM users WHERE id = ?", 
                (user_id,)
            )
            if not existing:
                self.logger.warning(f"UpdateUserPlugin: User with ID {user_id} not found.")
                return {"success": False, "error": f"User with ID {user_id} does not exist."}
            
            current_user = UserModel.from_row(existing[0])
        except Exception as e:
            self.logger.error(f"UpdateUserPlugin: Error querying user: {e}")
            return {"success": False, "error": "An internal error occurred."}

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
                "SELECT id, name, email FROM users WHERE id = ?", 
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
            user_msg = "An internal error occurred."

            if "UNIQUE constraint failed" in error_msg:
                user_msg = "Email is already in use by another user."
                self.logger.warning(f"UpdateUserPlugin: Attempt to use duplicate email: {email}")
            else:
                self.logger.error(f"UpdateUserPlugin: Error updating user: {error_msg}")

            return {"success": False, "error": user_msg}
