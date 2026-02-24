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
    
    async def shutdown(self):
        """Optional: Resource cleanup (close DB, stop server)"""
        pass