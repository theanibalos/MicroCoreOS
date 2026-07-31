# MicroCoreOS: The Architecture That Makes AI-Generated Code Maintainable

> The current solution to AI coding mistakes is more context — .cursorrules, CLAUDE.md, skills, system prompts.
> The result: context windows full of instructions instead of code.
>
> MicroCoreOS takes the opposite approach: an architecture where there's only one place to put things.

**1 file = 1 feature.** When AI makes a mistake, you find it in 30 seconds — not 30 minutes reviewing 8 files. The AI reads 2 files (the auto-generated system manifest + the plugin it's working on), follows one pattern, and produces clean, isolated code.

## The Elastic Monolith

MicroCoreOS is an **Elastic Monolith** built on an **Atomic Microkernel Architecture**:
a single process where business logic lives in atomic plugins (1 file = 1 feature) and
every piece of infrastructure is a swappable Tool behind a written contract — **in-process
by default, distributed on demand**.

Scaling is not a rewrite; it is a tool swap. The same plugins run unchanged whether the
event bus is in-memory or Kafka, the state store is a dict or Redis, the database is SQLite
or PostgreSQL. The kernel never knows which implementation is mounted — it only knows the
contract. This is the difference from a *modular monolith* (modules, but fixed infrastructure)
and from *microservices* (distributed from day one, whether you need it or not): an Elastic
Monolith starts as the simplest possible system and stretches piece by piece, only where
load demands it.

Proven today: SQLite ↔ PostgreSQL swap with identical plugin code, and a transport-driver
interface (`EventBusDriver`) where retries, DLQ, RPC and tracing are broker-agnostic —
Redis Streams, RabbitMQ, Kafka and a durable SQLite transport already shipped.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/microcoreos.svg)](https://pypi.org/project/microcoreos/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/theanibalos/MicroCoreOS/actions/workflows/ci.yml/badge.svg)](https://github.com/theanibalos/MicroCoreOS/actions)

---

## Quick Start

```bash
uv init my-app && cd my-app
uv add microcoreos
uv run microcoreos new .        # materialize tools/, domains/, plans/ as YOUR source
uv run microcoreos migrate      # apply DB migrations & generate AI_CONTEXT.md — DO THIS FIRST
uv run microcoreos              # boot
# Visit http://localhost:5000/docs
```

Or clone the repo to work on the framework itself:

```bash
git clone https://github.com/theanibalos/MicroCoreOS.git
cd MicroCoreOS
cp .env.example .env
uv run main.py                  # or: uv run microcoreos
```

No configuration needed. SQLite is the default (zero setup). The Kernel discovers all plugins, injects dependencies, runs migrations, and starts the server.

**Only the Kernel comes from the package.** Tools and domains are copied into your project, because installing and swapping infrastructure here is file placement — and you cannot move files inside `site-packages`. Optional infrastructure installs in one step:

```bash
uv run microcoreos add auth
```

| Command | What lands in your project | Needs a service |
|---|---|---|
| `add auth` | `tools/auth` + `domains/users` — register, login, who-am-I, logout | no |
| `add ping` | `domains/ping` — one `GET /ping`, the hello-world | no |
| `add postgres` | `tools/postgresql` — replaces SQLite as `db`, same API | yes |
| `add redis` | `tools/redis_state` — replaces the in-memory `state` | yes |
| `add s3` | `tools/s3` — object storage, presigned URLs | yes |
| `add scheduler` | `tools/scheduler` + `domains/scheduler` — cron and durable one-shots | no |
| `add kafka` | a driver into `tools/event_bus/` + `EVENT_BUS_DRIVER=kafka` | yes |
| `add rabbitmq` | a driver into `tools/event_bus/` + `EVENT_BUS_DRIVER=rabbitmq` | yes |
| `add chaos` | `tools/chaos` + `domains/chaos` — fault injection. Never in production | no |

`uv run microcoreos add` with no argument lists them too. Each one writes its
own `.env` keys and never overwrites a value you already set.

Use that rather than `uv add 'microcoreos[auth]'`. The extra is only the **dependency** — installing it alone leaves the source in `extras/`, where nothing discovers it, and the boot looks perfectly fine with the feature simply absent. `microcoreos add` does all three parts: the dependency, the source, and the `.env` keys.

### Development & AI Pipeline Commands

| Command | Purpose |
|---|---|
| `microcoreos status` | Reports active plan progress and `AI_CONTEXT.md` freshness |
| `microcoreos plan validate` | Validates active plan YAML (`plans/active_plan.yaml`) offline against 18 rules |
| `microcoreos migrate` | Applies SQL migrations AND regenerates `AI_CONTEXT.md` (the AI context manifest) |
| `microcoreos schema` | Inspects live database schema and normalized tables |

---

## One File = One Feature

This is a complete feature — schema, registration, logic, event publishing:

```python
# domains/products/plugins/create_product_plugin.py

from pydantic import BaseModel, Field
from microcoreos import BasePlugin

class CreateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(gt=0)

class CreateProductPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute,
                               tags=["Products"], request_model=CreateProductRequest)

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
            # Safe Error Reporting: log technically, respond safely.
            self.logger.error(f"Failed to create product: {e}")
            return {"success": False, "error": "Database operation failed"}
```

Drop this file in `domains/products/plugins/`, restart, and it works. No `main.py` edits, no route registration, no wiring.

---

## What Makes It Different

### 366 functional lines of kernel. Pure stdlib. No external dependencies in core.

The entire orchestration engine — DI, plugin discovery, tool lifecycle, fault tolerance — uses only Python's standard library.

That is the code your app depends on, and it is the whole of it: booting loads
`kernel`, `container`, `registry`, `context` and the two base classes, and
nothing else. The rest of the package — the scaffolder, the extras catalog,
`upgrade` — is the `microcoreos` command, build-time work that never executes
inside your application. `tests/test_core_purity.py` enforces both halves of
that: a third-party import in the kernel fails the suite, and so does the
kernel importing the CLI half.

### DI by parameter name.

```python
def __init__(self, db, http, logger):  # These ARE the injected tools
```

No decorators, no configuration, no container setup. The Kernel inspects your constructor, matches names to tools, done.

### AI_CONTEXT.md regenerates on every boot.

The system scans all tools, plugins, domains, events, and models — then writes a manifest with exact method signatures. Your AI always has current context, regardless of project size.

### Tools are swappable. Plugins don't change.

A Tool is identified by its `name` property. The SQLite tool and the PostgreSQL tool both expose the same API (`query`, `execute`, `transaction`, `health_check`) and both use `$1, $2` placeholders. To switch databases:

1. Change `name = "db"` in the SQLite tool to `name = "sqlite"`
2. Change `name = "postgresql"` in the PostgreSQL tool to `name = "db"`
3. Plugins don't change a single line.

Migrations are the honest exception: the `db` tool is not an ORM — SQL files run
**verbatim** on the active engine (no dialect translation), so an engine swap includes
one review pass over your migration SQL. The full procedure is in
[docs/ELASTIC_DEPLOYMENT.md](docs/ELASTIC_DEPLOYMENT.md) (Stage 1).

This pattern works for any infrastructure: swap the event bus backend, the HTTP server, the auth mechanism — as long as the new tool has the same `name` and API, plugins keep working.

Additional tools — PostgreSQL, Redis state, auth, S3, the scheduler, chaos — ship in `extras/` and install with `microcoreos add <name>`. If the new tool reuses an existing `name` (e.g. `redis_state` registers as `"state"`), move the tool it replaces out of `tools/` first: only one tool per name may be discovered.

The Redis state swap is verified by a parity suite (`tests/tools/test_state_parity.py`): the same contract battery runs against the in-memory reference and against a real Redis, so the replacement is proven equivalent, not assumed.

### Honest Kernel & Smart Infrastructure.

The Kernel is "logic-free." `ToolProxy` observes and reports health but **never retries automatically**, ensuring data integrity. Resilience is handled where the knowledge is: in the Tools (e.g., SQLite lock retries) or the Plugins (explicit logic).

---

## Built-in Observability (Zero Config)

**Causal Event Tracing** — Every event on the bus carries a `parent_id`. `GET /system/traces/tree` reconstructs the full causal chain. `GET /system/traces/stream` streams it live via SSE.

**Tool Call Metrics** — Every tool method call is automatically timed by ToolProxy. Access via `registry.get_metrics()` or attach a real-time sink.

**OpenTelemetry** (optional) — Set `OTEL_ENABLED=true`. Every tool call gets a span. Export to Jaeger, Grafana Tempo, Datadog. Zero changes to plugins.

---

## Architecture

```
MicroCoreOS/
├── microcoreos/             # the pip package — two halves that never mix
│   ├── kernel.py           # ┐ Discovery, DI, lifecycle
│   ├── container.py        # │ DI container + ToolProxy (Health/Metrics)
│   ├── registry.py         # │ Thread-safe system state
│   ├── context.py          # │ causality & Identity context      366 lines,
│   ├── base_plugin.py      # │ Plugin contract (11 lines)        pure stdlib —
│   ├── base_tool.py        # ┘ Tool contract (24 lines)          this is what
│   │                       #                                     your app loads
│   ├── cli.py              # ┐ The `microcoreos` command
│   ├── scaffold.py         # │ `new` — materializes your source
│   ├── catalog.py          # │ `add` — dependency + folders + .env
│   └── upgrade.py          # ┘ `upgrade` — the SHA-256 baseline
├── tools/                   # Stateless, swappable infrastructure
│   ├── http_server/        # FastAPI (REST + WebSocket + SSE)
│   ├── sqlite/             # Relational DB — isolation + smart retries
│   ├── event_bus/          # TTL + Retries + DLQ + Causal tracing
│   ├── telemetry/          # OpenTelemetry (optional)
│   └── ...                 # logger, state, config, registry
├── domains/                 # Business logic
│   ├── system/             # Observability endpoints
│   ├── devtools/           # Boot-time linters
│   └── {your_domain}/
├── extras/                  # Available, not installed — `microcoreos add`
│   ├── available_tools/    # auth, postgresql, redis_state, s3, scheduler...
│   └── available_domains/  # users (auth), ping, scheduler, chaos
└── AI_CONTEXT.md           # Auto-generated on every boot
```

---

## Problems It Addresses

| Problem                                 | Approach                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------ |
| **AI needs too many files for context** | 2 files: `AI_CONTEXT.md` + the plugin.                                         |
| **Coupling between modules**            | Domains communicate via EventBus only, never direct imports.                   |
| **Architecture erodes under pressure**  | Conventions are explicit and enforced.                                         |
| **Merge conflicts on shared files**     | Each feature is its own file. No shared business logic files.                  |
| **One dependency failure cascades**     | ToolProxy contains failures per-tool automatically.                            |
| **Changing databases takes weeks**      | Swap the tool file — same API, same placeholders — plus one review pass over migration SQL. |
| **Background errors disappear**         | EventBus watchdog + DLQ + causality engine.                                    |
| **Slow developer onboarding**           | Read `AI_CONTEXT.md` + one plugin.                                             |
| **Sync/async mixing bugs**              | Kernel auto-detects `def` vs `async def`, offloads sync to thread pool.        |

→ Deep dive: [docs.microcoreos.com/guide/problems](https://docs.microcoreos.com/guide/problems)

---

## Available Tools

| Tool        | Description                                                    |
| ----------- | -------------------------------------------------------------- |
| `http`      | FastAPI gateway — REST, WebSocket, SSE, auto-generated OpenAPI |
| `db`        | SQLite (default) or PostgreSQL — same API, drop-in swap at the tool-API level |
| `event_bus` | Pub/sub + RPC + TTL + Retries + DLQ + causal tracing. Transports swap by env var: in-process (default), SQLite (durable, survives restarts), Redis Streams (distributed); RabbitMQ in extras |
| `logger`    | Structured logging with sink pattern                              |
| `state`     | Thread-safe in-memory key-value store                             |
| `registry`  | Runtime introspection + metrics + health status                   |
| `telemetry` | OpenTelemetry — auto-instruments all tool calls                   |
| `config`    | Environment variable validation for plugins                       |
| `context_manager` | Regenerates `AI_CONTEXT.md` on every boot                    |

`auth` is not in that table on purpose: it is an extra. A fresh project has no
users table, no JWT and no `AUTH_SECRET_KEY` to set before it boots —
`microcoreos add auth` installs the tool plus register, login, who-am-I and
logout. `http` takes `auth_validator` as an optional callback and never imports
auth, so nothing in a default project misses it.

**Available as extras — `microcoreos add <name>` installs the dependency, moves
the source and writes the `.env` keys in one command:**

| Tool         | Description                                                              |
| ------------ | ------------------------------------------------------------------------ |
| `s3`         | AWS S3 object storage — private bucket + presigned URLs                  |
| `db`         | PostgreSQL — same API and placeholders as SQLite; swap procedure in [ELASTIC_DEPLOYMENT.md](docs/ELASTIC_DEPLOYMENT.md) |
| `state`      | Redis-backed state — drop-in swap for in-memory StateTool                |
| `rabbitmq`   | RabbitMQ **driver** for the Event Bus — transports swap by file, like tools: drop the `*_driver.py` into `tools/event_bus/` and set `EVENT_BUS_DRIVER=rabbitmq` |
| `scheduler`  | Cron jobs + in-memory one-shots (APScheduler) |
| `auth`       | JWT lifecycle + bcrypt hashing, plus register / login / who-am-I / logout |
| `kafka`      | Kafka **driver** for the Event Bus, same file-placement swap as RabbitMQ |
| `chaos`      | Fault injection and plugin pause/resume — never enable in production |
| `ping`       | A single `GET /ping`. The hello-world you read for the shape, then delete |

**Tools and the domains that need them.** The dependency runs one way — a
plugin cannot exist without its tool, but a tool stands on its own. So the
scheduler installs in two independent steps:

```bash
microcoreos add scheduler     # dependency + both folders + .env, in one command
```

Or by hand, which is what that command does:

```bash
uv add 'microcoreos[scheduler]'
mv extras/available_tools/scheduler tools/       # cron + in-memory one-shots
mv extras/available_domains/scheduler domains/   # durable one-shots (needs the above)
```

The tool keeps one-shots in memory by design: an arbitrary callable cannot
survive a restart, and a tool never uses other tools. The optional domain
composes `db + scheduler + event_bus` in the plugin layer to get durability,
and exposes it to any domain over the bus as `scheduler.one_shot.schedule` /
`scheduler.one_shot.cancel` — events that fire hours later and survive a restart.
It is also the reference example of that composition rule
(`.agent/workflows/new-tool.md`). Installing the domain without the tool fails
at boot, loudly: `Plugin scheduler.DurableOneShotsPlugin aborted: Missing tools: scheduler`.

---

## Working with AI

```
> Read AI_CONTEXT.md for available tools.
> Create a plugin in the orders domain that creates an order and publishes order.created.
```

The AI uses `$1, $2` placeholders, registers via `http`, publishes via `event_bus`, places everything in one file.

For full domains: follow `.agent/workflows/new-domain.md`.

---

## Testing

Constructor injection makes tests **black-box**: inject real in-memory tools
(SQLite `:memory:` with the domain migration applied, in-process event bus, real
auth) and mock only the tool whose failure you are forcing. A failing test then
pinpoints the plugin whose SQL or contract actually broke.

```python
@pytest.mark.anyio
@pytest.mark.migrations("users")
async def test_create_user_persists_and_publishes(db, event_bus, auth):
    # The fixtures are named after the Kernel's injection keys, so a test's
    # signature and its plugin's signature are the same vocabulary.
    plugin = CreateUserPlugin(http=MagicMock(), db=db, event_bus=event_bus,
                              logger=MagicMock(), auth=auth)

    result = await plugin.execute(
        {"name": "Ana", "email": "ana@example.com", "password": "password123"}
    )

    assert result["success"] is True
    row = await db.query_one("SELECT * FROM users WHERE id = $1", [result["data"]["id"]])
    assert await auth.verify_password("password123", row["password_hash"])  # stored hashed, never plain
```

Complete examples — happy paths, ownership (403), login throttling, error paths
that never leak technical detail — live in `tests/domains/users/`.

---

## Documentation

Full docs at **[docs.microcoreos.com](https://docs.microcoreos.com)**:
Quick Start · First Plugin Tutorial · Plugin Reference · Tools Reference · Observability · Philosophy

---

## Roadmap

Two tracks — see [ROADMAP.md](ROADMAP.md) for the full plan and decision log:

- **Monolith track**: route-collision & table-ownership linters, automatic test
  generation. `uv add microcoreos` shipped in 0.1.0 (ROADMAP Issue 39)
- **Distributed track**: event ACLs (Redis Streams, RabbitMQ, Kafka and the
  durable SQLite transport already shipped, all with crash-safe native
  delay via capability claims), runtime contracts via the schema catalog,
  distributed observability (export local, aggregate outside), transactional
  outbox (deferred until a real chain needs it)
- Tool distribution — shipped. Tools are **copied into your project**, not
  installed into site-packages: you own them and can edit them, and swapping
  stays what it is today, moving a file. Only the Kernel travels in the
  package, and `microcoreos upgrade` carries later fixes to the files you never
  touched. Release procedure: [docs/internal/RELEASING.md](docs/internal/RELEASING.md)

---

## License

[MIT](LICENSE)

---

**Anibal Fernandez** ([@theanibalos](https://github.com/theanibalos))
