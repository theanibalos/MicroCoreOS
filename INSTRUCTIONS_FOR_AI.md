# 🤖 AI Agent Guide: Building MicroCoreOS Plugins

This guide is for AI assistants (like Cursor, Claude, or ChatGPT) assisting in the development of MicroCoreOS.

## 🏗️ Architecture Philosophy: "Atomic Micro-Kernel"
MicroCoreOS follows a strict **Micro-Kernel** pattern.
- **Core (`/core`)**: Inmutable orchestrator. Never touched by plugins.
- **Tools (`/tools`)**: Stateless technical capabilities (e.g., `db`, `http`, `logger`).
- **Plugins (`/domains`)**: Stateful logic. The **ONLY** place where complexity lives.

## 🎯 The "1 File = 1 Feature" Rule
A plugin must be self-contained. It should handle its own validation, processing, and response.

### Core Logic Pattern
Follow this flow inside your `execute()` method:
1. **Validate**: Check inputs (Pydantic models + business rules).
2. **Process**: Prepare data or state changes.
3. **Act**: Perform the operation (e.g., `db.execute()`).
4. **Respond**: Return a standardized dict.

## 🛠️ Minimalist Plugin Template
Do not add imports for Tools. Request them directly in the constructor. The Kernel provides them as objects.

```python
from core.base_plugin import BasePlugin

class MyPlugin(BasePlugin):
    def __init__(self, http, db, logger, event_bus):
        # Tools are injected by name
        self.http = http
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        # Register routes and subscriptions
        self.http.add_endpoint("/path", "POST", self.handler)
        pass

    def execute(self, data: dict):
        # Pattern: Validate -> Process -> Act -> Respond
        self.logger.info("Executing logic...")
        return {"success": True, "data": {}}
    
    def handler(self, data: dict, context):
        return self.execute(data)
```

## ⚖️ Standards
- **Return Value**: Always return `{"success": bool, "data": Optional[dict], "error": Optional[str]}`.
- **Cross-Domain**: **NEVER** import from another domain. Use `event_bus.publish()` or `event_bus.request()`.
- **Stateless Tools**: Tools cannot hold business state. If you need to store global state, use the `state` tool.

---
*Refer to `AI_CONTEXT.md` for the current tool signatures.*
