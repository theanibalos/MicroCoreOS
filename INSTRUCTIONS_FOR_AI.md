# 🤖 AI Agent Implementation Guide

This guide is an "Interface Router" for AI agents. Do not read the whole document—jump to the section that matches your task.

## 🧭 Navigation Index
- **Task: New Plugin/Feature** → [See Plugins Section](#-new-plugin-single-feature)
- **Task: New Infrastructure** → [See Tools Section](#-new-tool-infrastructure)
- **Task: New Functional Area** → [See Domains Section](#-new-domain-functional-area)
- **Understanding Boot/Shutdown** → [See Lifecycle Section](#-system-lifecycle)
- **Need Inspiration?** → [See Reference Gallery](#-reference-gallery-elite-examples)

---

## 🧩 New Domain (Functional Area)
When creating a new domain (e.g., `billing`, `inventory`):
1. **Root**: `domains/{name}/`
2. **Markers**: Create `__init__.py` in the root.
3. **Hierarchy**:
   - `domains/{name}/models/`: Pydantic schemas and domain models.
   - `domains/{name}/plugins/`: Interaction logic and features.
4. **Encapsulation**: Domains **MUST NOT** import from each other. Use `event_bus`.

---

## ⚡ New Plugin (Single Feature)
**Goal**: Add logic using existing tools.
1. **Location**: `domains/{domain}/plugins/`
2. **Rule**: 1 File = 1 Feature.
3. **Usage Pattern**: Tools are injected via `__init__`. Use `self.tool_name` to interact.

```python
from core.base_plugin import BasePlugin

class MyPlugin(BasePlugin):
    def __init__(self, logger, event_bus, http, db):
        # 1. Dependency Injection (Save as instance attributes)
        self.logger = logger
        self.bus = event_bus
        self.http = http
        self.db = db

    def on_boot(self):
        # 2. Registration Phase (Executed only once)
        self.http.add_endpoint("/my-path", "POST", self.handler)
        self.bus.subscribe("user.created", self.execute)

    def execute(self, data: dict):
        # 3. Execution Phase (Business Logic)
        # Using tools:
        self.logger.info("New request received")
        result = self.db.query("SELECT * FROM users WHERE id=?", (data.get('id'),))
        return {"success": True, "data": result}
    
    def handler(self, data, context):
        return self.execute(data)
```

---

## 🔧 New Tool (Infrastructure)
**Goal**: Add technical capabilities.
1. **Location**: `tools/{name}/`
2. **Simple Tool**: Single file `{name}_tool.py` inside the folder.
3. **Complex Tool**: Use subfolders for migrations/configs if needed.

---

## 🔄 System Lifecycle
Understanding *when* code runs is critical.

### 🛠️ Tool Lifecycle
1. **`__init__`**: Instance created. Receives parameters from kernel (if any).
2. **`setup()`**: **Resource Allocation**. Connect to databases, load `.env`, start background engines.
3. **`on_boot_complete(container)`**: **Orchestration**. Executed when *all* tools are ready. Access other tools via `container.get('name')`.
4. **`shutdown()`**: **Cleanup**. Close sockets, stop threads, save remaining state.

### 🧩 Plugin Lifecycle
1. **`__init__`**: **DI Phase**. Just save the requested tools. Don't perform logic here.
2. **`on_boot()`**: **Subscription Phase**. Register HTTP endpoints or EventBus subscribers.
3. **`execute(data)`**: **Action Phase**. The standard entry point for logic.
4. **`shutdown()`**: **Cleanup**. Optional.

---

## 🏛️ Reference Gallery (Elite Examples)
If you are unsure how to implement a complex feature, study these high-quality plugins:

- **Standard CRUD + Events**: [create_user_plugin.py](domains/users/plugins/create_user_plugin.py)
- **WebSockets + EventBus Bridge**: [realtime_bridge.py](domains/ui/plugins/realtime_bridge.py)
- **Static File Serving**: [system_dashboard.py](domains/ui/plugins/system_dashboard.py)
- **System Observability & Registry**: [observability_plugin.py](domains/observability/plugins/observability_plugin.py)
- **Identity & JWT Protection**: [get_me_plugin.py](domains/users/plugins/get_me_plugin.py)

---
*Refer to `AI_CONTEXT.md` for live tool signatures and domain status.*
