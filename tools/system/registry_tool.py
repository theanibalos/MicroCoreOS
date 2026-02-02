from core.base_tool import BaseTool

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
