from core.base_plugin import BasePlugin

class CreateUserPlugin(BasePlugin):
    def execute(self, name, email):
        db = self.container.get("db")
        logger = self.container.get("logger")
        bus = self.container.get("event_bus") # <--- Obtenemos el bus

        try:
            logger.info(f"Intentando crear usuario: {email}")
            
            sql = "INSERT INTO users (name, email) VALUES (?, ?)"
            user_id = db.execute(sql, (name, email))
            
            # PUBLICAR EVENTO
            # No sabemos quién escucha, solo lanzamos el dato.
            bus.publish("user_created", {"name": name, "email": email})
            
            return {"success": True, "user_id": user_id}
            
        except Exception as e:
            logger.error(f"Error al crear usuario: {str(e)}")
            return {"success": False, "error": str(e)}