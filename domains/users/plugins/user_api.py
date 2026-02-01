from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel

class UserApiPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        """Registro de endpoints en FastAPI"""
        self.http.add_endpoint("/users/create", "POST", self.execute)
        self.logger.info("Plugin UserApi listo y registrado en FastAPI.")

    def execute(self, data: dict):
        """Lógica principal de creación de usuario"""
        name = data.get("name")
        email = data.get("email")

        # 1. Validación usando el Modelo
        ok, err = UserModel.validate_name(name)
        if not ok: 
            return {"success": False, "error": f"Nombre inválido: {err}"}

        ok, err = UserModel.validate_email(email)
        if not ok: 
            return {"success": False, "error": f"Email inválido: {err}"}

        # 2. Creación del objeto de dominio
        user = UserModel(name=name, email=email)
        
        # 3. Persistencia
        try:
            self.db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", 
                (user.name, user.email)
            )
            
            self.logger.info(f"Usuario {user.name} ({user.email}) creado exitosamente.")
            
            # 4. Notificación al Bus de Eventos
            self.bus.publish("user_created", user.to_dict())
            
            return {"success": True, "user": user.to_dict()}
            
        except Exception as e:
            self.logger.error(f"Error al guardar usuario en BD: {e}")
            return {"success": False, "error": "Error interno de base de datos"}