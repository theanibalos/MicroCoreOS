from abc import ABC
from core.context import current_event_id_var, current_identity_var

class BasePlugin(ABC):

    async def on_boot(self):
        """
        Lifecycle hook: executed when the plugin is loaded.
        Register endpoints, event subscriptions, etc.
        """
        pass

    async def execute(self, data: dict = None, context=None):
        """
        Optional entry point. Override only if the plugin has a
        single primary action (e.g., an HTTP handler).
        Event-driven plugins can skip this entirely.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not implement execute()")