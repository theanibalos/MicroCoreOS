from core.base_plugin import BasePlugin
from domains.users.models.user_model import UserModel, UserCreate, UserResponse

class CreateUserPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        # Registramos con soporte para Schemas
        self.http.add_endpoint(
            path="/users/create", 
            method="POST", 
            handler=self.execute, 
            tags=["Users"],
            request_model=UserCreate,
            response_model=UserResponse
        )
        self.logger.info("CreateUserPlugin: Endpoint /users/create registrado con Schema.")

    def execute(self, data: dict):
        name = data.get("name")
        email = data.get("email")

        try:
            # Insertar en base de datos
            user_id = self.db.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", 
                (name, email)from core.base_tool import BaseTool

class RegistryTool(BaseTool):
    """
    Proxy Tool que expone el Registro del Core a los Plugins.
    Actúa como un puente para mantener el desacoplamiento.
    """
    @property
    def name(self) -> str:
        return "registry"

    def setup(self):
        """No requiere estado propio, usa el del contenedor."""
        pass

    def get_interface_description(self) -> str:
        return "Acceso al Inventario Arquitectónico del Core (Herramientas, Dominios y Plugins)."

    def on_boot_complete(self, container):
        """Capturamos el registro real del contenedor."""
        self._core_registry = container.registry

    def get_system_dump(self) -> dict:
        """Delega en el registro del Core."""
        return self._core_registry.get_system_dump()

    def get_domain_metadata(self) -> dict:
        """Delega en el registro del Core."""
        return self._core_registry.get_domain_metadata()

            )
            
            user = UserModel(id=user_id, name=name, email=email)
            self.logger.info(f"Usuario {name} creado con ID {user_id}.")
            
            # Notificar al sistema
            self.bus.publish("users.created", user.to_dict())
            
            return {"success": True, "user": user.to_dict()}
        except Exception as e:
            error_msg = str(e)
            if "UNIQUE constraint failed" in error_msg:
                error_msg = "El correo electrónico ya está registrado."
                
            self.logger.error(f"Error en creación de usuario: {error_msg}")
            return {"success": False, "error": error_msg}
