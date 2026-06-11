# Elastic Deployment Guide — from single monolith to N replicas

MicroCoreOS is an **Elastic Monolith**: one codebase that runs as a single
process on a laptop and as N identical replicas behind a load balancer —
without changing a line of plugin code. Scaling is done by swapping tools
and flipping environment variables.

This guide is the operational path between those two extremes. Every step
is independently reversible.

---

## The three stages

| Stage | Persistence | State | Event transport | Replicas |
|-------|------------|-------|-----------------|----------|
| **Dev** (default) | SQLite | in-memory | in-process | 1 |
| **Small production** | PostgreSQL | in-memory | in-process | 1 |
| **Elastic** | PostgreSQL | Redis | Redis Streams | N |

You never skip a contract: every swap keeps the same tool `name` and the
same API, so plugins are untouched at every stage.

---

## Stage 1 — Single replica on PostgreSQL

1. **Swap the `db` tool** (both declare `name = "db"`; only one may live in `tools/`):
   ```bash
   mv tools/sqlite extras/available_tools/sqlite
   mv extras/available_tools/postgresql tools/postgresql
   ```
2. **Configure** (defaults in parentheses):
   ```bash
   PG_HOST=...        # (localhost)
   PG_PORT=...        # (5432)
   PG_USER=...        # (postgres)
   PG_PASSWORD=...
   PG_DATABASE=...    # (microcoreos)
   PG_MIN_POOL=...    PG_MAX_POOL=...    # pool sizing
   ```
3. **Run.** Migrations in `domains/*/migrations/*.sql` are applied on boot
   exactly as with SQLite (same topological sort, same `$1, $2` placeholders).

A single replica may keep the in-memory `state` tool and the in-process
event bus — they are correct as long as there is exactly one process.

---

## Stage 2 — N replicas

Three things break when you naively run two copies of any monolith:
shared volatile state, event delivery, and the scheduler. MicroCoreOS has
one switch for each.

### 2.1 Shared state → RedisStateTool

The in-memory `state` tool is per-process; counters and rate-limit windows
must move to Redis so the fleet shares them.

```bash
mv tools/state extras/available_tools/state
mv extras/available_tools/redis_state tools/redis_state
```

Configuration (shared with the bus driver — one Redis serves both):
```bash
REDIS_HOST=...              # (localhost)
REDIS_PORT=...              # (6379)
REDIS_DB=...                # (0)
REDIS_PASSWORD=...          # ("" = no auth)
REDIS_CONNECT_TIMEOUT=...   # (5 seconds)
```

### 2.2 Event transport → Redis Streams driver

No tool swap here — the driver is selected by env var, the EventBusTool
(retries, DLQ, RPC, tracing) stays exactly the same:

```bash
EVENT_BUS_DRIVER=redis_streams
EVENT_BUS_STREAM_MAXLEN=10000   # optional, approximate cap per stream
```

What you get across the fleet, with zero plugin changes:

- **Exactly-one-consumer per logical subscriber.** `subscribe()` derives a
  stable consumer group from the callback identity, so N replicas running
  the same plugin share one group — each event is handled by ONE replica.
  Distinct plugins get distinct groups, so each logical consumer still
  receives its copy.
- **At-least-once delivery.** Messages are acknowledged only after the
  handler (including bus-side retries) finishes. If a replica dies
  mid-handler, another replica of the group reclaims the message
  (XAUTOCLAIM, idle > 60s). Handlers must be idempotent — this was already
  the bus contract.
- **Causal traces survive the network.** Envelopes travel with `id` and
  `parent_id`; the causality tree crosses instances intact.

### 2.3 Scheduler → one beat, many workers

With N replicas, every cron job would fire N times. Designate exactly one
replica as the "beat":

```bash
# beat replica (exactly one)
SCHEDULER_ENABLED=true    # default

# worker replicas (all the others)
SCHEDULER_ENABLED=false
```

Jobs register everywhere (same code in every replica) but only fire on the
beat. For heavy jobs, the recommended pattern is: the job handler publishes
to the bus (`bus.publish("jobs.report.due")`) and workers consume — the
automatic consumer groups guarantee exactly-one-consumer across the fleet,
so the beat schedules and the fleet executes.

### 2.4 Migrations → pipeline step, not boot step

In production, migrations never run inside the replicas (a rolling deploy
would race N replicas against the same DDL). They run once, as a pipeline
step, before the new replicas start:

```bash
# all production replicas
DB_AUTO_MIGRATE=false

# CI/CD pipeline step (boots ONLY the db tool, migrates, exits)
DB_AUTO_MIGRATE=true uv run main.py --boot-tool db
```

This is the same model as Django/Rails/Flyway: the pipeline (with DBA
sign-off if required) owns the schema; replicas just connect.

---

## The edge layer (in front of the monolith)

These concerns belong to the reverse proxy / load balancer, **not** to
MicroCoreOS — putting them inside the app would waste a Python worker on
requests that should die at the door:

- **TLS termination** and HTTP→HTTPS redirect.
- **Load balancing** across the N replicas (any strategy works: the
  replicas are stateless once Stage 2 is complete — sessions live in the
  JWT, shared state lives in Redis).
- **Protecting the `/system/*` observability endpoints** (status, events,
  metrics, traces). They are public BY DESIGN — the framework does not
  impose an auth scheme on its own introspection; each deployment decides
  (block at the proxy, IP-allowlist, or add `auth_validator` in your fork).
- **Volumetric rate limiting** (per-IP, anti-abuse, DDoS). Example, nginx:

  ```nginx
  limit_req_zone $binary_remote_addr zone=perip:10m rate=10r/s;

  server {
      location / {
          limit_req zone=perip burst=20 nodelay;
          proxy_pass http://microcoreos_fleet;
      }
  }
  ```

  Identity-aware rate limiting (per-user, per-plan quotas) is the app's
  job because it needs business context — see the rate-limiting pattern in
  `INSTRUCTIONS_FOR_AI.md`, built on the `state` tool (already distributed
  after step 2.1).

---

## Full checklist (per replica)

```bash
# database (Stage 1 swap: tools/postgresql)
PG_HOST=db.internal  PG_PORT=5432  PG_USER=app  PG_PASSWORD=***  PG_DATABASE=microcoreos
DB_AUTO_MIGRATE=false                  # pipeline runs --boot-tool db

# shared state (Stage 2 swap: tools/redis_state) + event transport
REDIS_HOST=redis.internal  REDIS_PORT=6379  REDIS_PASSWORD=***
EVENT_BUS_DRIVER=redis_streams

# scheduler role
SCHEDULER_ENABLED=false                # true on exactly ONE replica

# http
HTTP_HOST=0.0.0.0  HTTP_PORT=8000
HTTP_CORS_ORIGINS=https://app.example.com

# auth
AUTH_SECRET_KEY=***                    # same key on ALL replicas (JWT must validate anywhere)

# observability (optional)
OTEL_ENABLED=true
OTEL_SERVICE_NAME=microcoreos
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

Deploy order: `--boot-tool db` in the pipeline → start/roll the worker
replicas → ensure exactly one beat replica is up.

---

## Verifying the elastic setup

1. Boot two replicas against the same Redis/PostgreSQL.
2. Create a user through replica A (`POST /users`).
3. Confirm the `user.created` handler (welcome service) ran on exactly ONE
   replica — not both, not zero.
4. Check `GET /system/traces/tree` on the handling replica: the causal tree
   must link the handler back to the original HTTP request envelope.
5. Kill a replica mid-load and repeat: pending messages are reclaimed by
   the surviving replica (at-least-once).

Known limits at this stage (tracked in `ROADMAP.md`):

- `GET /system/traces` is a per-instance ring buffer — cross-instance trace
  aggregation goes through OpenTelemetry (Issue 24).
- Event payload contracts are validated statically per instance; runtime
  validation on the bus is Issue 23.
