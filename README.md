# MicroCoreOS: Atomic Microkernel Architecture optimized for AI-Driven Development

> Every time I asked my AI to add a CRUD endpoint,  
> it tried to create 6-8 files. I got tired of it.

**1 file = 1 feature.** That's the entire idea.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
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

## The Solution: Atomic Microkernel

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

    async def execute(self, data: dict):
        try:
            user = UserEntity(**data)
            password_hash = self.auth.hash_password(user.password) if user.password else None
            user_id = await self.db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (user.name, user.email, password_hash)
            )
            await self.bus.publish("user.created", {"id": user_id, "email": user.email})
            return {"success": True, "data": {"id": user_id, "name": user.name}}
        except Exception as e:
            self.logger.error(f"Failed to create user: {e}")
            return {"success": False, "error": str(e)}

    async def handler(self, data: dict, context):
        return await self.execute(data)
```

**48 lines. One file. Complete feature.**

- ✅ Endpoint registration
- ✅ Database operation
- ✅ Event publishing
- ✅ Auto-discovered by the kernel
- ✅ Dependencies injected automatically

---

## For AI-Driven Development

The architecture generates `AI_CONTEXT.md` automatically—a manifest with all available tools and their exact method signatures. Your AI assistant always knows what's available without exploring the codebase. This allows for near-zero explanation when asking an AI to implement new features.

**Measured token usage per feature:**

The architecture minimizes "Context Noise". Every extra file in a traditional architecture is extra surface area for AI hallucinations and context saturation.

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
│   ├── http_server/        # Gateway with identity seeding
│   ├── sqlite/             # Async Persistence
│   └── event_bus/          # Tracer-enabled, monitored bus
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
| **Traceable** | Every event has a parent ID and an owner identity |
| **Observable** | No silent background failures (Event Watchdog) |

---

## Available Tools

| Tool | Description |
|------|-------------|
| `http_server` | REST endpoints with auto-generated OpenAPI |
| `db` | Database persistence — **SQLite** (default, zero-config) or **PostgreSQL** (production). Drop-in swap, zero plugin changes. |
| `event_bus` | Pub/sub and request/response patterns |
| `logger` | Structured logging with Sink support |
| `state` | Sharded in-memory key-value store |
| `registry` | Sharded high-concurrency architecture browser |
| `config` | Environment configuration |

---

## Advanced Design Decisions

### Tool vs Plugin: How to Decide?

```text
Is it a Tool or a Plugin?
├── Does it have domain state?              → Plugin
├── Is it reusable across domains?         → Tool  
└── Does it implement business rules?      → Plugin
```

**Example - Authentication:**  
- Verifying token signature (crypto) → **Tool** (technical, stateless)  
- Managing users and permissions → **Plugin** (domain state, business rules)

### Events: Sync vs Async

| Method | When to use | Example |
|--------|-------------|---------|
| `publish(event, data)` | Fire and forget (no confirmation needed) | Notifications, logs, side-effects |
| `request(event, data)` | Need a response to continue (RPC) | Cross-domain validations, queries |

### Observability: The Watchdog
In most async architectures, background tasks die quietly. MicroCoreOS includes a **Monitoring Callback** native to the EventBus:
- **Zero Silent Failures**: Every task spawned by an event is watched. If an async subscriber crashes, the system captures and logs it immediately.
- **Causality Engine**: Using `ContextVars` in a neutral `core/context.py`, the system tracks the "Identity Chain". You know exactly which HTTP Request caused which background event.

> [!WARNING]
> Abuse of `request()` reintroduces coupling. If a Plugin makes too many requests to another, they probably belong in the same domain.

### Boot Lifecycle

```text
Boot Sequence:
1. Tool.setup()            → Internal initialization
2. Plugin.__init__()       → Dependency injection  
3. Plugin.on_boot()        → Register endpoints, subscriptions
4. Tool.on_boot_complete() → Actions requiring the full system
5. System Online           → Ready for requests
6. Tool.shutdown()         → Graceful resource cleanup
```

---

## Anti-Patterns (The "Don'ts")

| ❌ Anti-Pattern | ✅ Solution |
|----------------|------------|
| Plugin imports another Plugin | Communicate via EventBus |
| Plugin accesses Container directly | Declare dependency in `__init__` |
| Tool containing business logic | Move to a Plugin in the appropriate domain |
| Shared state without a Tool | Use the `state` Tool with namespaces |

---

## High Performance & Production

If your implementation requires extreme performance (game engines, 4K video processing, or HFT):

### 1. Zero-Copy Architecture
To handle large data volumes between plugins without overhead:
* **Ownership Pointers**: In languages like **Rust**, use `Arc` (Atomic Reference Counting). This allows multiple plugins to read the **same physical memory** simultaneously without copying a single byte.

### 2. Static Dispatch
Dynamic DI has a small "indirection" cost. For instant speed:
* **Code Generation**: Use tools to generate the dependency wiring at compile-time. This allows the compiler to perform *Inlining*, eliminating call overhead.

### 3. Selection by Latency

| Language | Profile | Ideal for... |
|----------|---------|---------------|
| **Python** | Context-Efficient | Rapid Prototyping, APIs, AI Logic |
| **Go** | Throughput-Optimal | High-traffic Microservices |
| **Rust** | Latency-Extreme | Engines, Video, Real-time Systems |

---

## Roadmap

MicroCoreOS is moving towards a fully decentralized, marketplace-driven ecosystem:

- 🏗️ **Atomic Tool Marketplace**: A drop-in ecosystem where tools (Redis, PostgreSQL, LLMs) are self-contained folders with their own manifests, default configs, and AI instructions.
- 🔍 **Tracer Tool**: Integrated mapping of which plugins react to which events for full observability.
- 🌐 **Polyglot Kernels**: Support for sidecar plugins via gRPC or WASM for language-agnostic development.
- 📦 **One-Click Distribution**: Install new capabilities via `uv` or simply by copying a folder into `/tools`.

---

## Why "Not Invented Here"?

MicroCoreOS implements its own DI and orchestration deliberately:
* **Why not FastAPI/Flask directly?**: To reduce the API surface an AI needs to learn. The "Framework" is the code you see in `/core`—100% auditable.
* **Why not external Injectors?**: To maintain transparency. The Kernel is an orchestrator you can read in one minute and understand exactly how your tools are wired.

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

- **Zero-Friction Quickstart**: The default `db` Tool uses SQLite (a local file), and the `event_bus` uses memory. Anyone can clone and run the project immediately without Docker or external dependencies.
- **Infinite Horizontal Scaling**: Need to scale to 10 servers? Drop in a `redis_event_bus` Tool or a `rabbitmq_tool`. Need a robust database? Swap the SQLite `db` folder for the PostgreSQL `db` folder. **Your Plugins won't change a single line.** Both tools register as `"db"`, accept the same `$1, $2...` placeholders, and expose the identical API. The SQLite tool converts placeholders internally.
- **Honest about swapping**: Not every tool swap is zero-change. Some engines are fundamentally different (SQL vs NoSQL, REST vs GraphQL). But even in the worst case, the delta is cheap—your AI rewrites a plugin in seconds. The architecture ensures the blast radius is always **one file**.
- **In the age of cheap code**: The SQL is the cheapest part of your feature. Your AI rewrites it instantly. Why over-abstract it?

### Same Isolation, Less Ceremony


| Traditional Benefit | MicroCoreOS Equivalent |
|--------------------|-----------------------|
| "Change DB without touching logic" | Change the Tool, not the Plugin |
| "Test layers in isolation" | Mock Tools in plugin tests |
| "Clear ownership boundaries" | 1 plugin = 1 owner |
| "Onboarding new devs" | Read AI_CONTEXT.md in 5 minutes |
| "High Concurrency" | Sharded Registry Locks |
| "End-to-end Traceability" | Native Context Engine |

### Testing without Gymnastics

Because dependencies are injected via the constructor, you mock them directly using standard tools. We use **AnyIO** for seamless async/sync testing:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from domains.users.plugins.create_user_plugin import CreateUserPlugin

@pytest.mark.anyio  # Hybrid-ready testing
async def test_create_user_success():
    mock_db = AsyncMock()
    mock_db.execute.return_value = 42
    
    plugin = CreateUserPlugin(
        http=MagicMock(),
        db=mock_db,
        event_bus=AsyncMock(),
        logger=MagicMock(),
        auth=MagicMock()
    )

    result = await plugin.execute({"name": "Test", "email": "a@b.com"})
    assert result["success"] is True
    assert result["data"]["id"] == 42
```





---

## Translations

- [Español](docs/translations/es/README.md)

---

## License

[MIT](LICENSE) - Simple and permissive.

For commercial consulting or support: theanibalos@gmail.com

---

## Author

**AnibalOS** ([@theanibalos](https://github.com/theanibalos))

Built because I was tired of explaining my architecture to Claude.

---
