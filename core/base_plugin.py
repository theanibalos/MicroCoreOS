from abc import ABC

class BasePlugin(ABC):

    async def on_boot(self):
        """
        Lifecycle hook: executed when the plugin is loaded.
        Register endpoints, event subscriptions, etc.
        """
        pass

    async def shutdown(self):
        """Optional cleanup hook."""
        pass
