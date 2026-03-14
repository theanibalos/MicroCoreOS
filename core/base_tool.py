from abc import ABC, abstractmethod

class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def setup(self):
        pass

    @abstractmethod
    def get_interface_description(self) -> str:
        pass

    async def on_boot_complete(self, container):
        """Optional hook: executed when everything is loaded."""
        pass

    async def on_instrument(self, tracer_provider) -> None:
        """Optional hook: called by TelemetryTool to instrument the tool's underlying framework.
        Override to add driver-level spans (e.g. FastAPIInstrumentor, asyncpg instrumentation).
        Runs on the raw tool instance, bypassing ToolProxy, so failures won't mark the tool DEAD.
        """
        pass

    async def shutdown(self):
        """Optional: Resource cleanup (close DB, stop server)"""
        pass