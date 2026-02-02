from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel

class CreateUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint("/users/create", "POST", self.execute, tags=["Users"])
        self.logger.info("CreateUserPlugin: Endpoint /users/create registrado.")

    def execute(self, data: dict):
        name = data.get("name")
        email = data.get("email")

        ok, err = UserModel.validate_name(name)
        if not ok: return {"success": False, "error": f"Nombre inválido: {err}"}

        ok, err = UserModel.validate_email(email)
        if not ok: return {"success": False, "error": f"Email inválido: {err}"}

        try:
            user_id = self.db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", 
                (name, email)
            )
            
            user = UserModel(id=user_id, name=name, email=email)
            self.logger.info(f"Usuario {name} creado con ID {user_id}.")
            self.bus.publish("user_created", user.to_dict())
            
            return {"success": True, "user": user.to_dict()}
        except Exception as e:
            self.logger.error(f"Error en creación: {e}")
            return {"success": False, "error": str(e)}
