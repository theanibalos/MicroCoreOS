# MicroCoreOS Documentation

## For building plugins and domains

- `AI_CONTEXT.md` — Quick start, all tools with signatures, active domain inventory
- `INSTRUCTIONS_FOR_AI.md` — Anti-patterns, new domain/plugin/tool guides, testing

## Deep reference docs

| Document | What it covers |
|----------|---------------|
| [EVENT_BUS.md](EVENT_BUS.md) | Full event bus reference, causality tracking, failure handling, anti-patterns for event hell |
| [HTTP_SERVER.md](HTTP_SERVER.md) | All HTTP capabilities: REST, SSE, WebSocket, auth, CORS, security headers, X-Request-ID |
| [CORE_INFRASTRUCTURE.md](CORE_INFRASTRUCTURE.md) | Kernel, Container, ToolProxy, metrics, ContextVars, Registry, undocumented tool behaviors |
| [OBSERVABILITY.md](OBSERVABILITY.md) | All observability endpoints, telemetry layers, frontend integration guide |
| [OBSERVABILITY_API.md](OBSERVABILITY_API.md) | Exact data contract (JSON shapes, SSE framing) of every `/system/*` endpoint — for external dashboards |
| [ELASTIC_DEPLOYMENT.md](ELASTIC_DEPLOYMENT.md) | Operational path from single monolith to N replicas: tool swaps, env flags, migrations pipeline, edge layer |

## Available Extras

Pre-built tools and domains not active by default. See the **Available Extras** section in `INSTRUCTIONS_FOR_AI.md` for activation instructions.

| Extra | Type | Purpose |
|-------|------|---------|
| `extras/available_tools/postgresql/` | Tool | Production PostgreSQL — drop-in swap for the default SQLite `db` tool |
| `extras/available_tools/chaos/` | Tool | Chaos engineering — intentional boot failure to test Kernel fault tolerance |
| `tools/s3/` | Tool | AWS S3 storage — private bucket + presigned URLs pattern |
| `extras/available_domains/chaos/` | Domain | Kernel resilience plugins — blocking boot, crashing endpoint, stress tests |
