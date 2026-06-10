# 📜 SYSTEM MANIFEST

> This file is ALL you need to build a plugin. For advanced topics (testing, observability, creating tools), see [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).

## ⚡ Plugin Quick Start

**Location**: `domains/{domain}/plugins/{feature}_plugin.py` — 1 file = 1 feature.

### Template

```python
from typing import Optional
from pydantic import BaseModel, Field
from core.base_plugin import BasePlugin

# Request/Response schemas live HERE, not in models/
class CreateThingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class ThingData(BaseModel):
    id: int
    name: str

class CreateThingResponse(BaseModel):
    success: bool
    data: Optional[ThingData] = None
    error: Optional[str] = None

class CreateThingPlugin(BasePlugin):
    def __init__(self, http, db, event_bus, logger):
        self.http = http
        self.db = db
        self.bus = event_bus
        self.logger = logger

    async def on_boot(self):
        self.http.add_endpoint(
            "/things", "POST", self.execute,
            tags=["Things"],
            request_model=CreateThingRequest,
            response_model=CreateThingResponse,
        )

    async def execute(self, data: dict, context=None):
        try:
            req = CreateThingRequest(**data)
            thing_id = await self.db.execute(
                "INSERT INTO things (name) VALUES ($1) RETURNING id", [req.name]
            )
            await self.bus.publish("thing.created", {"id": thing_id})
            return {"success": True, "data": {"id": thing_id, "name": req.name}}
        except Exception as e:
            # Technical error logged server-side, safe message for client
            self.logger.error(f"Failed to create thing: {e}")
            return {"success": False, "error": "Database error"}
```

### New Domain Structure

```
domains/{name}/
  __init__.py
  models/{name}.py        <- Entity: DB mirror only (Pydantic BaseModel)
  migrations/001_xxx.sql  <- Raw SQL, auto-executed on boot
  plugins/                <- 1 file = 1 feature
```

### Critical Rules

1. **Never modify `main.py`** — Kernel auto-discovers everything.
2. **DI by name** — `__init__` param names must match tool `name` properties.
3. **Schemas inline** — Request AND response schemas go in the plugin file, not in `models/`.
4. **No cross-domain imports** — Use `event_bus` for inter-domain communication.
5. **Return format** — Always `{"success": bool, "data": ..., "error": ...}`.
6. **Use `Field`** — Never bare `str`/`int` in request schemas. Use `Field(min_length=1)` etc.
7. **SQL placeholders** — Always `$1, $2, $3...` (never `?`).
8. **Always pass `response_model=`** to `add_endpoint` — generates OpenAPI docs.
9. **Never expose sensitive fields** — Define response schema with only safe fields.
10. **No hardcoded imports** — Never `from tools.x import X`. Use DI.

---

## 🛠️ Quick Architecture Ref
- **Pattern**: `__init__` (DI) -> `on_boot` (Register) -> handler methods (Action).
- **Injection**: Tools are injected by name in the constructor.

## 🛠️ Available Tools
Check method signatures before implementation.

### 🔧 Tool: `auth` (Status: ✅)
```text
Authentication Tool (auth):
        - PURPOSE: Manage system security, password hashing, and JWT token lifecycle.
        - CAPABILITIES:
            - await hash_password(password: str) -> str: Securely hashes a plain-text
                password using bcrypt. Async — runs in a thread (bcrypt is CPU-bound).
            - await verify_password(password: str, hashed_password: str) -> bool:
                Verifies if a password matches its hash. Async — runs in a thread.
            - create_token(data: dict, expires_delta: Optional[int] = None) -> str:
                Generates a JWT signed token. 'data' should contain claims (e.g. {'sub': user_id}).
                'expires_delta' is optional minutes until expiration.
            - decode_token(token: str) -> dict:
                Verifies and decodes a JWT token. Returns the payload dictionary.
                Raises TokenExpiredError / InvalidTokenError / AuthError on failure.
            - validate_token(token: str) -> dict | None:
                Safe, non-throwing token validation. Returns the decoded payload
                if valid, or None if expired/invalid. Ideal for middleware guards.
```

### 🔧 Tool: `config` (Status: ✅)
```text
Configuration Tool (config):
        - PURPOSE: Validated access to environment variables for plugins.
          Tools read their own env vars with os.getenv() — this tool is for plugins.
        - CAPABILITIES:
            - get(key, default=None, required=False) -> str | None:
                Returns the value of the environment variable.
                If required=True and the variable is not set, raises EnvironmentError.
            - require(*keys) -> None:
                Validates that all specified variables are set.
                Call in on_boot() to fail early with a clear error message.
                Example: self.config.require("STRIPE_KEY", "SENDGRID_KEY")
```

### 🔧 Tool: `event_bus` (Status: ✅)
```text
Universal Event Bus (event_bus):
        - publish(event_name, data, **kwargs): Broadcast an event.
        - subscribe(event_name, callback, group=None, retries=0, backoff=0.5): Listen for events.
        - request(event_name, data, timeout=5): Async RPC (returns dict).
        - unsubscribe(event_name, callback): Stop listening.
        - get_trace_history() -> List[TraceNode]: Last 500 event records.
        - get_subscribers() -> dict: Current subscriber map.
        - add_listener(callback): Sink for all events (record: dict).
        - add_failure_listener(callback): Sink for errors (record: dict).
        
        CRITICAL: Subscribing callbacks receive an 'EventEnvelope' object.
        Example: async def on_event(self, event: EventEnvelope): print(event.payload)
        
        RETRIES & IDEMPOTENCY:
        - If 'retries' > 0, the handler will be re-executed on failure with exponential backoff.
        - Ensure handlers are idempotent as they may run multiple times.

        DEAD-LETTER QUEUE (DLQ):
        - Final failures are published to '_dlq.<original_event>'.
        - Payload includes 'original' envelope, 'subscriber', 'error', and 'attempts'.
        - Loop protection: '_dlq.*', '_reply.*', and wildcard events are never dead-lettered.
        - Toggle via EVENT_BUS_DLQ_ENABLED (default: true).

        UNIVERSAL CAPABILITIES (kwargs):
        - key: String. For strict ordering (Kafka/SQS).
        - priority: Integer (1-10). Importance (RabbitMQ).
        - delay: Integer (seconds). Delivery schedule.
        - ttl: Float (seconds). Message expiration hint.
        - correlation_id: String. Cross-reference for RPC.

        RESILIENCE:
        - A subscriber that reaches 5 consecutive FINAL failures for a specific event is auto-unsubscribed.
```

### 🔧 Tool: `http` (Status: ✅)
```text
HTTP Server Tool (http):
        - PURPOSE: FastAPI-powered HTTP gateway. Supports REST, static files, WebSockets and SSE.
        - HANDLER SIGNATURE: async def execute(self, data: dict, context: HttpContext) -> dict
          'data' = flat merge of [path params] + [query params] + [body/form fields].
          Special keys in 'data':
            - data["_auth"]: contains the payload from auth_validator if successful.
            - data["_files"]: list of FastAPI UploadFile objects (only if has_files=True).
        - SECURITY DEFAULTS:
            - Cookies set via context.set_cookie are 'Secure=True', 'HttpOnly=True', 'SameSite=Lax'.
            - CSRF Guard: Mutations (POST/PUT/DELETE) using cookie auth REQUIRE 'X-Requested-With' header.
        - CAPABILITIES:
            - add_endpoint(path, method, handler, tags=None, request_model=None,
                           response_model=None, auth_validator=None, has_files=False):
                - has_files: if True, enables multipart/form-data. Request model fields 
                  become Form fields. To use a file: file = data["_files"][0]; 
                  await s3.upload_fileobj(file.filename, file.file, content_type=file.content_type)
            - mount_static(path, directory_path): Serve static files from a directory.
            - add_ws_endpoint(path, on_connect, on_disconnect=None): WebSocket support.
            - add_sse_endpoint(path, generator, tags=None, auth_validator=None): 
                Server-Sent Events. generator yields formatted strings: "data: {...}\n\n".
        - HttpContext CAPABILITIES (inside handler):
            - context.set_status(code: int): Override HTTP status (default: 200).
            - context.redirect(url: str, status=302): Redirect to another URL.
            - context.set_cookie(key, value, max_age=3600, ...): Set secure response cookie.
            - context.set_header(key, value): Add custom response header.
            - context.set_binary_response(content: bytes, media_type: str): Return raw file.
        - RESPONSE CONTRACT:
            - Standard: return {"success": bool, "data": ..., "error": ...}
            - WARNING: All values in 'data' must be JSON-serializable. Pydantic model 
              instances are NOT serializable — always call .model_dump() before returning.
```

### 🔧 Tool: `telemetry` (Status: ✅)
```text
Telemetry Tool (telemetry):
        - PURPOSE: OpenTelemetry distributed tracing. Auto-instruments all tool calls via ToolProxy.
          No changes needed in plugins or existing tools to get basic spans.
        - ACTIVATION: Set OTEL_ENABLED=true. Degrades gracefully if disabled or packages missing.
        - ENV VARS:
            - OTEL_ENABLED: "true" to activate (default: "false").
            - OTEL_SERVICE_NAME: Service name in traces (default: "microcoreos").
            - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP/gRPC endpoint (e.g. "http://jaeger:4317").
              If not set, traces are printed to console (development mode).
        - CAPABILITIES:
            - get_tracer(scope: str) -> Tracer: Named tracer for custom spans inside a plugin.
                Usage: tracer = self.telemetry.get_tracer("my_plugin")
                       with tracer.start_as_current_span("my_operation"): ...
                Returns a no-op tracer if OTel is disabled — safe to use unconditionally.
        - AUTO-INSTRUMENTATION (zero config):
            Every tool call (db.execute, event_bus.publish, auth.create_token, etc.)
            gets a span automatically via ToolProxy. No plugin changes needed.
        - DRIVER-LEVEL INSTRUMENTATION (optional, per tool):
            Tools can implement on_instrument(tracer_provider) in BaseTool to add
            framework-specific spans (SQL query text, HTTP route, etc.).
        - INSTALL:
            uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

### 🔧 Tool: `context_manager` (Status: ✅)
```text
Context Manager Tool (context_manager):
        - PURPOSE: Automatically manages and generates live AI contextual documentation.
        - CAPABILITIES:
            - Reads the system registry.
            - Exports active tools, health status, and domain models to AI_CONTEXT.md.
            - Regenerates AI_CONTEXT.md on every boot — always up to date with the live system.
```

### 🔧 Tool: `logger` (Status: ✅)
```text
Logging Tool (logger):
        - PURPOSE: Record system events and business activity for audit and debugging.
        - CAPABILITIES:
            - info(message): General information.
            - error(message): Critical failures.
            - warning(message): Non-critical alerts.
            - add_sink(callback): Connect external observability (e.g. to EventBus).
                Sink signature: callback(level: str, message: str, timestamp: str, identity: str)
                'identity' is the current plugin/tool context (from current_identity_var).
                Use it to attribute errors to specific plugins for health tracking.
```

### 🔧 Tool: `state` (Status: ✅)
```text
Key-Value State Tool (state):
        - PURPOSE: Share volatile global data between plugins safely.
        - IDEAL FOR: Counters, temporary caches, rate-limit windows, business semaphores.
        - CONTRACT: All methods are async. Values must be JSON-serializable so the
          tool can be swapped for a distributed store (Redis) without touching plugins.
        - TTL: optional expiry in seconds. Expired keys behave like missing keys.
          On increment(), the TTL only applies when the key is created (fixed window).
        - CAPABILITIES:
            - await set(key, value, namespace='default', ttl=None): Store a value.
            - await get(key, default=None, namespace='default'): Retrieve a value (None if missing).
            - await has(key, namespace='default'): Returns True if key exists.
            - await keys(namespace='default'): Returns list of all live keys in the namespace.
            - await get_all(namespace='default'): Returns a deep copy of all live key-value pairs.
            - await increment(key, amount=1, namespace='default', ttl=None): Atomic increment.
              Starts at 0. Returns the new value.
            - await delete(key, namespace='default'): Delete a key (no-op if missing).
            - await clear(namespace='default'): Remove all keys in the namespace.
```

### 🔧 Tool: `registry` (Status: ✅)
```text
Systems Registry Tool (registry):
        - PURPOSE: Introspection and discovery of the system's architecture at runtime.
        - CAPABILITIES:
            - get_system_dump() -> dict: Full inventory of active Tools, Domains and Plugins.
                Returns:
                {
                  "tools": {
                    "<tool_name>": {"status": "OK"|"FAIL"|"DEAD", "message": str|None}
                  },
                  "plugins": {
                    "<PluginClassName>": {
                      "status": "BOOTING"|"RUNNING"|"READY"|"DEAD",
                      "error": str|None,
                      "domain": str,
                      "class": str,
                      "dependencies": ["tool_name", ...]  # tools injected in __init__
                    }
                  },
                  "domains": { ... }
                }
                NOTE: status is updated REACTIVELY via ToolProxy (hybrid policy):
                ToolUnavailableError -> DEAD immediately; any other exception ->
                DEAD only after 5 consecutive failures (success resets the streak).
                A tool that silently stopped responding may still show "OK".
            - get_domain_metadata() -> dict: Detailed analysis of models and schemas.
            - get_metrics() -> list[dict]: Last 1000 tool call records.
                Each record: {tool, method, duration_ms, success, timestamp}.
                Use to build /system/metrics or feed into an observability sink.
            - add_metrics_sink(callback): Register a sink for real-time metric records.
                Signature: callback(record: dict).
                Called synchronously on every tool method call — keep it fast.
            - update_tool_status(name, status, message=None): Manually override a tool's health status.
                status: "OK" | "FAIL" | "DEAD".
                Intended for health-check plugins that verify tools proactively.
```

### 🔧 Tool: `db` (Status: ✅)
```text
Async SQLite Persistence Tool (sqlite):
        - PURPOSE: Drop-in replacement for PostgreSQL. Lightweight relational data
          storage using SQLite with async access. Accepts PostgreSQL-style placeholders
          ($1, $2...) and converts them transparently to SQLite's native '?'.
        - PLACEHOLDERS: Use $1, $2, $3... (SAME as PostgreSQL — swap-compatible).
        - CAPABILITIES:
            - await query(sql, params?) → list[dict]: Read multiple rows (SELECT).
            - await query_one(sql, params?) → dict | None: Read a single row (SELECT).
            - await execute(sql, params?) → int | None: Write data (INSERT/UPDATE/DELETE).
              With RETURNING (SQLite 3.35+): returns the first column value.
              INSERT without RETURNING: returns lastrowid. Others: returns affected row count.
            - await execute_many(sql, params_list) → None: Batch writes.
            - async with transaction() as tx: Explicit transaction block with auto-commit/rollback.
              Inside tx: tx.query(), tx.query_one(), tx.execute() — same signatures.
            - await health_check() → bool: Verify database connectivity.
        - EXCEPTIONS: Raises DatabaseError or DatabaseConnectionError on failure.
        - MIGRATIONS: SQL files in domains/*/migrations/*.sql are auto-applied on boot via
          topological sort (alphabetical by default). To declare that one migration must
          run before another, add as the first comment line:
            "-- depends: other_domain/001_file.sql"
          Works for same-domain or cross-domain dependencies. .sql extension is optional.
```

### 🔧 Tool: `scheduler` (Status: ✅)
```text
Scheduler Tool (scheduler):
        - PURPOSE: Background job scheduling — cron-style recurring jobs and one-shot timed jobs.
          Backed by APScheduler AsyncIOScheduler. Zero infrastructure required.
          Supports both async and sync callbacks transparently.
        - CAPABILITIES:
            - add_job(cron_expr: str, callback, job_id?: str) -> str:
                Schedule a recurring job with a 5-field cron expression.
                e.g. "*/5 * * * *" = every 5 min, "0 9 * * 1-5" = weekdays at 09:00.
                Returns job_id (auto-generated if not provided).
                Providing a stable job_id prevents duplicates on restart.
            - add_one_shot(run_at: datetime, callback, job_id?: str) -> str:
                Schedule a one-time job at a specific datetime (timezone-aware).
                Returns job_id.
            - remove_job(job_id: str) -> bool:
                Remove a job by ID. Returns True if removed, False if not found.
            - list_jobs() -> list[dict]:
                Snapshot of all scheduled jobs: [{id, next_run, trigger}].
        - REGISTER IN on_boot(): jobs are collected during on_boot(), scheduler starts
          in on_boot_complete() after all plugins have registered.
        - SWAP: replace with Celery beat by creating a new tool with name = "scheduler"
          and the same 4-method API. Plugins do not change.
```

### 🔧 Tool: `s3` (Status: ✅)
```text
S3 Storage Tool (s3):
        - PURPOSE: AWS S3 object storage. Private bucket + presigned URLs pattern.
          Compatible with LocalStack and MinIO via AWS_S3_ENDPOINT_URL.
          External tool — setup() never raises; methods fail gracefully if unavailable.
        - SIZE LIMITS:
            Controlled by env vars (AWS_S3_SIZE_LIMIT_ENABLED, AWS_S3_MAX_FILE_SIZE_MB).
            Override per call with max_size_bytes=N. Raises S3FileSizeError if exceeded.
            If size limit is disabled globally, max_size_bytes is also ignored.
        - All methods accept an optional bucket= param. If omitted, uses AWS_S3_DEFAULT_BUCKET.
        - CAPABILITIES:
            - await upload_fileobj(key, fileobj, bucket?, content_type?, metadata?) -> str:
                Upload a file-like object (e.g. FastAPI UploadFile). Streams to S3.
            - await upload_file(key, file_path, bucket?, content_type?, metadata?, max_size_bytes?) -> str:
                Upload a file from disk. Returns the key.
            - await upload_bytes(key, data: bytes, bucket?, content_type?, metadata?, max_size_bytes?) -> str:
                Upload bytes from memory. Returns the key.
            - await download_file(key, destination_path, bucket?) -> bool:
                Download an object to a local path.
            - await download_bytes(key, bucket?) -> bytes:
                Download an object into memory.
            - await get_presigned_url(key, bucket?, expires_in=3600, operation='get'|'put') -> str:
                Generate a temporary signed URL. Use for serving private media to clients.
            - await delete_object(key, bucket?) -> bool:
                Delete an object.
            - await list_objects(prefix='', bucket?, max_keys=1000) -> list[dict]:
                List objects. Each dict: {key, size, last_modified, etag}.
            - await object_exists(key, bucket?) -> bool:
                Check existence without downloading.
            - await copy_object(src_key, dst_key, src_bucket?, dst_bucket?) -> bool:
                Copy between keys or buckets.
            - await get_object_metadata(key, bucket?) -> dict:
                Returns {size, content_type, last_modified, etag, metadata}.
            - await health_check() -> bool:
                Verify S3 connectivity.
        - EXCEPTIONS: S3Error, S3UnavailableError, S3FileSizeError.
```

## 📦 Domains

### `ping`
- **Tables**: none
- **Endpoints**: GET /ping
- **Events emitted**: none
- **Events consumed**: none
- **Dependencies**: http, logger
- **Plugins**: ping.PingPlugin

### `system`
- **Tables**: none
- **Endpoints**: GET /system/events, GET /system/metrics, GET /system/status, GET /system/traces/flat, GET /system/traces/tree, SSE /system/events/stream, SSE /system/logs/stream, SSE /system/metrics/stream, SSE /system/traces/stream
- **Events emitted**: `event.delivery.failed` ()
- **Events consumed**: none
- **Dependencies**: config, container, event_bus, http, logger, registry
- **Plugins**: system.ArchitectureLinterPlugin, system.EventDeliveryMonitorPlugin, system.SystemEventsPlugin, system.SystemEventsStreamPlugin, system.SystemLogsStreamPlugin, system.SystemMetricsPlugin, system.SystemStatusPlugin, system.SystemTracesPlugin, system.SystemTracesStreamPlugin, system.ToolHealthPlugin

### `users`
- **Table `user`**: name (str), email (EmailStr), password_hash (any)
- **Endpoints**: DELETE /users/{user_id}, GET /users, GET /users/me, GET /users/{user_id}, POST /auth/login, POST /auth/logout, POST /users, PUT /users/{user_id}
- **Events emitted**: `user.created` (email, id), `user.deleted` (id), `welcome.notify.sent` (email, user_id)
- **Events consumed**: user.created
- **Dependencies**: auth, db, event_bus, http, logger, state
- **Plugins**: users.CreateUserPlugin, users.DeleteUserPlugin, users.GetMePlugin, users.GetUserByIdPlugin, users.ListUsersPlugin, users.LoginPlugin, users.LogoutPlugin, users.UpdateUserPlugin, users.WelcomeServicePlugin

