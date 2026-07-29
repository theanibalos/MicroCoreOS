# MicroCoreOS Documentation

## For building plugins and domains

- `AI_CONTEXT.md` — Quick start, all tools with signatures, active domain inventory
- `INSTRUCTIONS_FOR_AI.md` — Anti-patterns, new domain/plugin/tool guides, testing
- `.agent/workflows/` — Scale ladder: feature-plan → new-domain → multi-domain-plan → new-tool
- `plans/` — The active plan: `active_plan.yaml` (contract) + `active_plan.md` (checklist)

## Deep reference docs

| Document | What it covers |
|----------|---------------|
| [TECH_DEBT.md](TECH_DEBT.md) | What is knowingly unfinished and what it would cost to finish — verified, not suspected |
| [CLI.md](CLI.md) | The `microcoreos` command: `new`, `add`, `upgrade`, `run`, `dev` — flags, what each one writes, and why |
| [PARALLEL_DEVELOPMENT.md](PARALLEL_DEVELOPMENT.md) | N agents building in parallel without collisions: phases, formal plan format v3 (crash points, failure planes), the 16 validity rules and `POST /system/plan/validate` |
| [EVENT_BUS.md](EVENT_BUS.md) | Full event bus reference, causality tracking, failure handling, anti-patterns for event hell |
| [HTTP_SERVER.md](HTTP_SERVER.md) | All HTTP capabilities: REST, SSE, WebSocket, auth, CORS, security headers, X-Request-ID |
| [CORE_INFRASTRUCTURE.md](CORE_INFRASTRUCTURE.md) | Kernel, Container, ToolProxy, metrics, ContextVars, Registry, undocumented tool behaviors |
| [OBSERVABILITY.md](OBSERVABILITY.md) | All observability endpoints, telemetry layers, frontend integration guide |
| [OBSERVABILITY_API.md](OBSERVABILITY_API.md) | Exact data contract (JSON shapes, SSE framing) of every `/system/*` endpoint — for external dashboards |
| [ELASTIC_DEPLOYMENT.md](ELASTIC_DEPLOYMENT.md) | Operational path from single monolith to N replicas: tool swaps, env flags, migrations pipeline, edge layer |

## Available Extras

Pre-built tools and domains not active by default. Install one with
`microcoreos add <extra>` — it handles the dependency, the folders and the
`.env` settings in one command. The manual equivalent, and what breaks if you
skip a step: the **Available Extras** section in `INSTRUCTIONS_FOR_AI.md`.

| Extra | Type | Dependency | Purpose |
|-------|------|-----------|---------|
| `extras/available_tools/postgresql/` | Tool | `[postgres]` | Production PostgreSQL — drop-in swap for the default SQLite `db` tool |
| `extras/available_tools/redis_state/` | Tool | `[redis]` | Distributed state — drop-in swap for the in-memory `state` tool |
| `extras/available_tools/s3/` | Tool | `[s3]` | AWS S3 storage — private bucket + presigned URLs pattern |
| `extras/available_tools/scheduler/` | Tool | `[scheduler]` | Cron jobs + in-memory one-shots (APScheduler) |
| `extras/available_tools/chaos/` | Tool | none | Chaos engineering — intentional boot failure to test Kernel fault tolerance |
| `extras/available_tools/kafka/` | Driver | `[kafka]` | Kafka transport for the Event Bus — drop the `*_driver.py` into `tools/event_bus/` |
| `extras/available_tools/rabbitmq/` | Driver | `[rabbitmq]` | RabbitMQ transport for the Event Bus — same drop-in procedure |
| `extras/available_domains/scheduler/` | Domain | requires the scheduler **tool** | Durable one-shots — the `scheduler.one_shot.*` bus API, survives restarts |
| `extras/available_domains/chaos/` | Domain | requires the chaos **tool** | Kernel resilience plugins — blocking boot, crashing endpoint, stress tests |
