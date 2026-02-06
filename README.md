# MicroCoreOS

> Every time I asked my AI to add a CRUD endpoint,  
> it tried to create 6-8 files. I got tired of it.

**1 file = 1 feature.** That's the entire idea.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## The Problem

AI assistants like Cursor and Claude need to understand your architecture to add features.

In traditional layered architectures, that means explaining:
- Where to put the entity
- How to wire the repository
- Which factory creates the use case
- How the controller maps to the route
- What DTOs to create

**That's 6-8 files and 200+ lines of code for one endpoint.**

## The Solution

```python
# domains/products/plugins/create_product_plugin.py
from core.base_plugin import BasePlugin

class CreateProductPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute)

    def execute(self, data: dict):
        product_id = self.db.execute(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            (data["name"], data["price"])
        )
        self.bus.publish("product.created", {"id": product_id})
        return {"success": True, "id": product_id}
```

**48 lines. One file. Complete feature.**

- ✅ Endpoint registration
- ✅ Database operation
- ✅ Event publishing
- ✅ Auto-discovered by the kernel
- ✅ Dependencies injected automatically

---

## For AI-Driven Development

The architecture generates `AI_CONTEXT.md` automatically—a manifest with all available tools and their signatures. Your AI assistant always knows what's available without exploring the codebase.

**Measured token usage per feature:**

| Architecture | Files | Lines | Est. Tokens |
|--------------|-------|-------|-------------|
| **MicroCoreOS** | 1 | ~50 | ~1,000 |
| Vertical Slice | 2-3 | ~100 | ~1,500 |
| N-Layer | 4-5 | ~150 | ~2,500 |
| Hexagonal | 5-7 | ~200 | ~3,500 |
| Clean Architecture | 6-8 | ~250 | ~4,000 |

---

## Quick Start

```bash
git clone https://github.com/theanibalos/MicroCoreOS.git
cd MicroCoreOS
uv run main.py
# Visit http://localhost:5000/docs
```

---

## Project Structure

```
MicroCoreOS/
├── core/                    # The micro-kernel (~240 lines total)
│   ├── kernel.py           # Orchestrator with autodiscovery
│   ├── container.py        # Thread-safe DI container
│   ├── base_plugin.py      # Plugin contract (13 lines)
│   └── base_tool.py        # Tool contract (23 lines)
├── tools/                   # Infrastructure (stateless)
│   ├── http_server/        # FastAPI wrapper
│   ├── sqlite/             # Database abstraction
│   └── event_bus/          # Decoupled communication
├── domains/                 # Business logic
│   └── {domain}/
│       ├── plugins/        # Use cases (1 file = 1 feature)
│       └── models/         # Domain models
└── AI_CONTEXT.md           # Auto-generated for AI assistants
```

---

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Blind Kernel** | The kernel knows nothing about business logic |
| **Tool = Stateless** | Tools provide technical capabilities |
| **Plugin = Stateful** | Plugins contain business logic |
| **Event-Driven** | Plugins communicate via EventBus only |
| **Declarative DI** | Declare deps in constructor, kernel delivers |

---

## Available Tools

| Tool | Description |
|------|-------------|
| `http_server` | REST endpoints with auto-generated OpenAPI |
| `db` | SQLite abstraction (query, execute) |
| `event_bus` | Pub/sub and request/response patterns |
| `logger` | Structured logging |
| `state` | In-memory key-value store |
| `config` | Environment configuration |

---

## For Teams

In traditional architectures, a single feature requires coordination:
- Someone owns the domain layer
- Someone owns the infrastructure
- Someone wires the dependency injection
- Someone reviews cross-layer changes

**In MicroCoreOS: 1 person, 1 file, 1 PR.**

### Why Tools are Stateless

Tools don't hold business state—they're pure infrastructure. This means:

- **Swap databases instantly**: Replace the `db` Tool with PostgreSQL, MongoDB, or an ORM. Plugins don't change.
- **No migration risk**: Tools are interchangeable by design.
- **In the age of cheap code**: Your AI writes the SQL in 2 seconds. Why abstract it?

### Same Isolation, Less Ceremony

| Traditional Benefit | MicroCoreOS Equivalent |
|--------------------|-----------------------|
| "Change DB without touching business logic" | Change the Tool, not the Plugin |
| "Test layers in isolation" | Mock Tools in plugin tests |
| "Clear ownership boundaries" | 1 plugin = 1 owner |
| "Onboarding new devs" | Read AI_CONTEXT.md in 5 minutes |

---

## Translations

- [Español](docs/translations/es/README.md)

---

## License

[AGPL-3.0](LICENSE) - Free to use, modifications must be open-sourced if deployed as a service.

For commercial licensing: contact@theanibalos.dev

---

## Author

**Antonio Ibalos** ([@theanibalos](https://github.com/theanibalos))

Built because I was tired of explaining my architecture to Claude.

---

*If this saves you time, consider giving it a ⭐*
