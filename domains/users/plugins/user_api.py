from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel

class UserApiPlugin(BasePlugin):
    def on_boot(self):
        """Registro del endpoint en la Tool HTTP"""
        http = self.container.get("http_server")
        http.add_endpoint("/users/create", "POST", self.create_user_handler)

    def create_user_handler(self, data):
        """Bridge entre HTTP y la lógica del Plugin"""
        return self.execute(**data)

    def execute(self, **kwargs):
        # --- 1. VALIDACIÓN SOBERANA (El Plugin decide qué pedir al Modelo) ---
        name = kwargs.get("name")
        email = kwargs.get("email")

        # El plugin valida campo por campo usando la lógica centralizada del Modelo
        ok, err = UserModel.validate_name(name)
        if not ok: 
            return {"success": False, "error": f"Nombre inválido: {err}"}

        ok, err = UserModel.validate_email(email)
        if not ok: 
            return {"success": False, "error": f"Email inválido: {err}"}

        # --- 2. LÓGICA DE NEGOCIO (Uso del Modelo como DTO) ---
        user = UserModel(name=name, email=email)
        
        # --- 3. PERSISTENCIA ---
        db = self.container.get("db")
        logger = self.container.get("logger")
        
        try:
            db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", 
                (user.name, user.email)
            )
            
            logger.info(f"Usuario {user.name} registrado vía API.")
            
            # --- 4. NOTIFICACIÓN (Event Bus) ---
            bus = self.container.get("event_bus")
            bus.publish("user_created", user.to_dict())
            
            return {"success": True, "data": user.to_dict()}
            
        except Exception as e:
            logger.error(f"Fallo en DB al crear usuario: {e}")
            return {"success": False, "error": "Error interno al guardar"}