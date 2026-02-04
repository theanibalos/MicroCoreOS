from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserUpdateWithId, UserResponse

class UpdateUserPlugin(BasePlugin):
    """
    Plugin para actualizar usuarios existentes.
    - Guarda cambios en base de datos
    - Publica evento users.updated
    - Registra logs de operación
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
        self.logger.info("UpdateUserPlugin: Endpoint /users/update registrado con Schema.")

    def execute(self, data: dict):
        user_id = data.get("id")
        name = data.get("name")
        email = data.get("email")

        # 1. Validar: Verificar que el usuario existe
        try:
            existing = self.db.query(
                "SELECT id, name, email FROM users WHERE id = ?", 
                (user_id,)
            )
            if not existing:
                self.logger.warning(f"UpdateUserPlugin: Usuario con ID {user_id} no encontrado.")
                return {"success": False, "error": f"Usuario con ID {user_id} no existe."}
            
            current_user = UserModel.from_row(existing[0])
        except Exception as e:
            self.logger.error(f"UpdateUserPlugin: Error consultando usuario: {e}")
            return {"success": False, "error": str(e)}

        # 2. Validar campos si fueron proporcionados
        if name is not None:
            valid, error = UserModel.validate_name(name)
            if not valid:
                self.logger.warning(f"UpdateUserPlugin: Validación de nombre fallida: {error}")
                return {"success": False, "error": f"Nombre inválido: {error}"}
        
        if email is not None:
            valid, error = UserModel.validate_email(email)
            if not valid:
                self.logger.warning(f"UpdateUserPlugin: Validación de email fallida: {error}")
                return {"success": False, "error": f"Email inválido: {error}"}

        # 3. Procesar: Construir query dinámico solo con campos proporcionados
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if email is not None:
            updates.append("email = ?")
            params.append(email)
        
        if not updates:
            self.logger.warning("UpdateUserPlugin: No se proporcionaron campos para actualizar.")
            return {"success": False, "error": "No se proporcionaron campos para actualizar."}
        
        params.append(user_id)
        
        # 4. Actuar: Ejecutar actualización en base de datos
        try:
            self.db.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            
            # Obtener usuario actualizado
            updated_row = self.db.query(
                "SELECT id, name, email FROM users WHERE id = ?", 
                (user_id,)
            )
            updated_user = UserModel.from_row(updated_row[0])
            
            self.logger.info(f"UpdateUserPlugin: Usuario {user_id} actualizado correctamente.")
            
            # Publicar evento al sistema
            self.bus.publish("users.updated", {
                "user_id": user_id,
                "changes": {
                    "name": name if name is not None else current_user.name,
                    "email": email if email is not None else current_user.email
                },
                "previous": current_user.to_dict()
            })
            
            # 5. Responder
            return {"success": True, "user": updated_user.to_dict()}
            
        except Exception as e:
            error_msg = str(e)
            if "UNIQUE constraint failed" in error_msg:
                error_msg = "El correo electrónico ya está en uso por otro usuario."
            
            self.logger.error(f"UpdateUserPlugin: Error actualizando usuario: {error_msg}")
            return {"success": False, "error": error_msg}
