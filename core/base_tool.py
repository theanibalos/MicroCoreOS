from abc import ABC, abstractmethod

class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def get_interface_description(self) -> str:
        pass

    def on_boot_complete(self, container):
        """Optional hook: executed when everything is loaded."""
        pass
    
    def shutdown(self):
        """Optional: Resource cleanup (close DB, stop server)"""
        pass