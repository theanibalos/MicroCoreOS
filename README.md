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

- **Zero-Friction Quickstart**: The default `db` Tool uses SQLite, and the `event_bus` uses memory. Anyone can clone and run the project immediately without Docker or external dependencies.
- **Infinite Horizontal Scaling**: Need to scale to 10 servers? Drop in a `redis_event_bus` Tool or a `rabbitmq_tool`. Need a robust database? Swap SQLite for PostgreSQL. **Your Plugins (business logic) won't change a single line.** The Kernel handles the new wiring.
- **No migration risk**: Tools are interchangeable by design.
- **In the age of cheap code**: Your AI writes the SQL in 2 seconds. Why abstract it?

### Same Isolation, Less Ceremony


| Traditional Benefit | MicroCoreOS Equivalent |
|--------------------|-----------------------|
| "Change DB without touching logic" | Change the Tool, not the Plugin |
| "Test layers in isolation" | Mock Tools in plugin tests |
| "Clear ownership boundaries" | 1 plugin = 1 owner |
| "Onboarding new devs" | Read AI_CONTEXT.md in 5 minutes |





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
