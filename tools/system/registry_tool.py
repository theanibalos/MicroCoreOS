from core.base_tool import BaseTool

class RegistryTool(BaseTool):
    """
    Proxy Tool that exposes the Core Registry to Plugins.
    Receives the registry reference at registration time via Container,
    so it is available immediately in on_boot() — no timing dependency.
    """
    def __init__(self):
        self._core_registry = None

    @property
    def name(self) -> str:
        return "registry"

    def _set_core_registry(self, registry):
        """Called by Container.register() before any plugin boots."""
        self._core_registry = registry

    def setup(self):
        pass

    def get_interface_description(self) -> str:
        return """
        Systems Registry Tool (registry):
        - PURPOSE: Introspection and discovery of the system's architecture at runtime.
        - CAPABILITIES:
            - get_system_dump() -> dict: Full inventory of active Tools, Domains and Plugins.
                Returns:
                {
                  "tools": {
                    "<tool_name>": {"status": "OK"|"FAIL"|"DEAD", "message": str|None}
                  },
                  "plugins": {
                    "<PluginClassName>": {
                      "status": "BOOTING"|"RUNNING"|"READY"|"DEAD",
                      "error": str|None,
                      "domain": str,
                      "class": str,
                      "dependencies": ["tool_name", ...]  # tools injected in __init__
                    }
                  },
                  "domains": { ... }
                }
                NOTE: status is updated REACTIVELY (on exception via ToolProxy).
                A tool that silently stopped responding may still show "OK".
            - get_domain_metadata() -> dict: Detailed analysis of models and schemas.
        """

    def get_system_dump(self) -> dict:
        if not self._core_registry:
            return {"tools": {}, "domains": {}, "plugins": {}}
        return self._core_registry.get_system_dump()

    def get_domain_metadata(self) -> dict:
        if not self._core_registry:
            return {}
        return self._core_registry.get_domain_metadata()
