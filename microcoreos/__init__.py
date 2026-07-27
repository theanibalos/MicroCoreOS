"""
MicroCoreOS — the public address of the framework.

Plugins and tools import from HERE, never from the file that happens to define
a name today:

    from microcoreos import BasePlugin, BaseTool, ToolUnavailableError

`Kernel`, `Container` and `Registry` stay in their submodules on purpose: they
are boot-time machinery (`main.py`, tests), not plugin surface.
"""

from microcoreos.base_plugin import BasePlugin
from microcoreos.base_tool import BaseTool, ToolUnavailableError
from microcoreos.context import current_event_id_var, current_identity_var

__all__ = [
    "BasePlugin",
    "BaseTool",
    "ToolUnavailableError",
    "current_event_id_var",
    "current_identity_var",
]
