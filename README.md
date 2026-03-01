# MicroCoreOS: Atomic Microkernel Architecture optimized for AI-Driven Development

> Every time I asked my AI to add a CRUD endpoint,  
> it tried to create 6-8 files. I got tired of it.

**1 file = 1 feature.** That's the entire idea.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## The Problem

AI assistants need to understand your architecture to add features.

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
from pydantic import BaseModel
from core.base_plugin import BasePlugin

class CreateProductRequest(BaseModel):  # schema lives in the plugin, not in models/
    name: str
    price: float

class CreateProductPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute, tags=["Products"],
                               request_model=CreateProductRequest)

    async def execute(self, data: dict, context=None):
        try:
            req = CreateProductRequest(**data)
            product_id = await self.db.execute(
                "INSERT INTO products (name, price) VALUES ($1, $2) RETURNING id",
                [req.name, req.price]
            )
            await self.bus.publish("product.created", {"id": product_id})
            return {"success": True, "data": {"id": product_id, "name": req.name}}
        except Exception as e:
            self.logger.error(f"Failed to create product: {e}")
            return {"success": False, "error": str(e)}
```

**30 lines. One file. Complete feature.**

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

### How the AI Documentation Works

The documentation is designed for **minimal reads, zero redundancy**:

| File | What it does | When it's read |
|------|-------------|----------------|
| `AI_CONTEXT.md` | Live inventory of tools + method signatures | **Auto-generated** on every boot |
| `CLAUDE.md` / `SKILL.md` | Rules + plugin template | **Auto-loaded** by the AI agent at start |
| `INSTRUCTIONS_FOR_AI.md` | Deep reference (lifecycle, tools, edge cases) | **On demand** — rare tasks only |
| `.agent/workflows/` | Step-by-step recipes (e.g. `/new-domain`) | **On demand** — triggered by the user |

**To write a plugin**, the AI reads exactly 2 files:
1. `AI_CONTEXT.md` → what tools exist and their signatures
2. `domains/{domain}/models/{entity}.py` → the DB table structure

That's it. No `main.py`, no core files, no framework docs. The fewer files the AI reads, the fewer it hallucinates.

### Building with MicroCoreOS

MicroCoreOS is designed for AI-assisted development. Copy these prompts directly into Claude, Cursor, or any AI agent.

**Add a feature to an existing domain:**
> Add a plugin to the `{domain}` domain that `{describe what it does}`.
> Read `AI_CONTEXT.md` for available tools and `domains/{domain}/models/` for the data structure.

**Create a new domain from scratch:**
> Use the `/new-domain` workflow to create a `{name}` domain with these fields: `{list fields}`.
> Read `AI_CONTEXT.md` first.

**Create a new infrastructure Tool:**
> Create a new Tool called `{name}` that wraps `{technology/library}`.
> Read `AI_CONTEXT.md` and `INSTRUCTIONS_FOR_AI.md` for the Tool template.

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
├── core/                    # The micro-kernel (~340 lines total)
│   ├── kernel.py           # Orchestrator with autodiscovery
│   ├── container.py        # DI container + ToolProxy monitoring
│   ├── registry.py         # Sharded-lock architecture browser
│   ├── context.py          # ContextVars for causality tracking
│   ├── base_plugin.py      # Plugin contract (15 lines)
│   └── base_tool.py        # Tool contract (23 lines)
├── tools/                   # Infrastructure (stateless, drop-in)
│   ├── http_server/        # FastAPI-powered REST + WebSocket gateway
│   ├── sqlite/             # Async SQLite (default, zero-config)
│   ├── postgresql/         # Async PostgreSQL (production)
│   ├── event_bus/          # Pub/Sub + Async RPC with tracing
│   ├── auth/               # JWT + bcrypt authentication
│   ├── logger/             # Structured logging with Sink support
│   ├── state/              # Sharded in-memory key-value store
│   ├── config/             # Environment configuration for plugins
│   ├── context/            # AI_CONTEXT.md auto-generator
│   └── ...                 # chaos, system, registry tools
├── domains/                 # Business logic
│   └── {domain}/
│       ├── plugins/        # Use cases (1 file = 1 feature)
│       ├── models/         # Domain models (Pydantic)
│       └── migrations/     # SQL migration scripts
└── AI_CONTEXT.md           # Auto-generated manifest for AI assistants
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
| **Hybrid Async** | Supports `async` and `sync`; kernel offloads sync to threads automatically |
| **Traceable** | Every event has a parent ID and an owner identity via `ContextVars` |
| **Observable** | No silent background failures (ToolProxy + Event Watchdog) |
| **AI-Native** | `AI_CONTEXT.md` auto-generated on every boot for AI assistants |

---

## Available Tools

| Tool | Description |
|------|-------------|
| `http` | FastAPI-powered REST + WebSocket gateway with auto-generated OpenAPI |
| `db` | Database persistence — **SQLite** (default, zero-config) or **PostgreSQL** (production). Drop-in swap, zero plugin changes. |
| `event_bus` | Pub/sub and async RPC with built-in tracing |
| `auth` | JWT token lifecycle + bcrypt password hashing |
| `logger` | Structured logging with Sink support |
| `state` | Sharded in-memory key-value store |
| `registry` | Sharded-lock architecture introspection |
| `config` | Environment configuration for plugins |
| `context_manager` | Auto-generates `AI_CONTEXT.md` from live system state |
| `chaos` | Chaos engineering — intentional boot failures for fault tolerance testing |

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

## Performance Characteristics

MicroCoreOS is designed for **developer velocity**, not raw throughput. That said, the architecture includes several performance-conscious decisions:

- **Hybrid Async Engine**: The Kernel automatically offloads synchronous plugin methods to threads via `asyncio.to_thread`, ensuring the event loop is never blocked.
- **Sharded Registry Locks**: The `Registry` uses per-category locks (`tools`, `plugins`, `domains`) to reduce contention during concurrent boot and runtime updates.
- **ToolProxy Monitoring**: Tool calls are wrapped in a transparent proxy that detects failures and updates the Registry in real-time — zero overhead on the happy path.
- **Parallel Boot**: All tools are initialized concurrently via `asyncio.gather`. Plugins boot in parallel after tool setup.

---

## Roadmap

MicroCoreOS is moving towards a fully decentralized, marketplace-driven ecosystem:

- 🏗️ **Atomic Tool Marketplace**: A drop-in ecosystem where tools (Redis, LLMs, Stripe) are self-contained folders with their own manifests, default configs, and AI instructions.
- 🔍 **Visual Tracer**: Integrated mapping of which plugins react to which events for full observability.
- 🌐 **Polyglot Kernels**: Support for sidecar plugins via gRPC or WASM for language-agnostic development.
- 📦 **One-Click Distribution**: Install new capabilities via `uv` or simply by copying a folder into `/tools`.
- 🦀 **Language Ports**: The architecture is language-agnostic by design. Future ports to Go and Rust can leverage static dispatch and zero-copy patterns for extreme-latency use cases.

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

@pytest.mark.anyio  # Hybrid async/sync testing
async def test_create_user_success():
    mock_db = AsyncMock()
    mock_db.execute.return_value = 42  # Simulates RETURNING id
    
    plugin = CreateUserPlugin(
        http=MagicMock(),       # Tools injected by name
        db=mock_db,
        event_bus=AsyncMock(),
        logger=MagicMock(),
        auth=MagicMock()
    )

    result = await plugin.execute({"name": "Test", "email": "a@b.com"})
    assert result["success"] is True
    assert result["data"]["id"] == 42
    mock_db.execute.assert_called_once()  # Verify DB was called
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

Built because I was tired of explaining my architecture to IA.

---
