from abc import ABC, abstractmethod

class BasePlugin(ABC):
    def on_boot(self):
        """
        Optional: Executed when the plugin is loaded.
        Ideal for subscribing to events.
        """
        pass

    @abstractmethod
    def execute(self, **kwargs):
        pass