from core.base_tool import BaseTool

class RegistryTool(BaseTool):
    """
    Proxy Tool that exposes the Core Registry to Plugins.
    Acts as a bridge to maintain decoupling.
    """
    @property
    def name(self) -> str:
        return "registry"

    def setup(self):
        """Does not require its own state, uses the container's."""
        pass

    def get_interface_description(self) -> str:
        return "Access to the Core's Architectural Inventory (Tools, Domains, and Plugins)."

    def on_boot_complete(self, container):
        """Capture the real registry from the container."""
        self._core_registry = container.registry

    def get_system_dump(self) -> dict:
        """Delegates to the Core registry."""
        return self._core_registry.get_system_dump()

    def get_domain_metadata(self) -> dict:
        """Delegates to the Core registry."""
        return self._core_registry.get_domain_metadata()
