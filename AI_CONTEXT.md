# 📜 SYSTEM MANIFEST

> **NOTICE:** This is a LIVE inventory. For implementation guides, read [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).

## 🏗️ Quick Architecture Ref
- **Pattern**: `__init__` (DI) -> `on_boot` (Register) -> handler methods (Action).
- **Injection**: Tools are injected by name in the constructor.

## 🛠️ Available Tools
Check method signatures before implementation.

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
Async Event Bus Tool (event_bus):
        - PURPOSE: Non-blocking communication between plugins. Pub/Sub and Async RPC.
        - SUBSCRIBER SIGNATURE: async def handler(self, data: dict)
        - CAPABILITIES:
            - await publish(event_name, data): Fire-and-forget broadcast.
            - await subscribe(event_name, callback): Register a subscriber.
                Use event_name='*' for wildcard (observability only, no RPC).
            - await unsubscribe(event_name, callback): Remove a subscriber.
            - await request(event_name, data, timeout=5): Async RPC.
                The subscriber must return a non-None dict.
            - get_trace_history() -> list: Last 500 event records with causality data.
```

### 🔧 Tool: `http` (Status: ✅)
```text
HTTP Server Tool (http):
        - PURPOSE: FastAPI-powered HTTP gateway. Supports REST, static files, and WebSockets.
        - HANDLER SIGNATURE: async def execute(self, data: dict, context: HttpContext) -> dict
          'data' = flat merge of path params + query params + body.
          'context' = HttpContext for set_status(), set_cookie(), set_header().
        - CAPABILITIES:
            - add_endpoint(path, method, handler, tags=None, request_model=None,
                           response_model=None, auth_validator=None):
                Buffers a route for registration. Supports Pydantic models for validation
                and OpenAPI schema generation.
                auth_validator: async fn(token: str) -> dict | None
                  → returned payload is injected into data["_auth"].
            - mount_static(path, directory_path): Serve static files.
            - add_ws_endpoint(path, on_connect, on_disconnect=None): WebSocket endpoint.
        - RESPONSE CONTRACT: return {"success": bool, "data": ..., "error": ...}
          Use context.set_status(N) to override HTTP status code (default: 200).
```

### 🔧 Tool: `chaos` (Status: ✅)
```text
Chaos Engineering Tool (chaos):
        - PURPOSE: Intentionally fails during boot to verify Kernel fault tolerance.
        - Enabled by setting CHAOS_ENABLED=true in the environment.
        - No capabilities exposed to plugins.
```

### 🔧 Tool: `context_manager` (Status: ✅)
```text
Context Manager Tool (context_manager):
        - PURPOSE: Automatically manages and generates live AI contextual documentation.
        - CAPABILITIES:
            - Reads the system registry.
            - Exports active tools, health status, and domain models to AI_CONTEXT.md.
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
```

### 🔧 Tool: `state` (Status: ✅)
```text
In-Memory State Tool (state):
        - PURPOSE: Share volatile global data between plugins safely.
        - IDEAL FOR: Counters, temporary caches, and shared business semaphores.
        - CAPABILITIES:
            - set(key, value, namespace='default'): Store a value.
            - get(key, default=None, namespace='default'): Retrieve a value.
            - increment(key, amount=1, namespace='default'): Atomic increment.
            - delete(key, namespace='default'): Delete a key.
```

### 🔧 Tool: `registry` (Status: ✅)
```text
Systems Registry Tool (registry):
        - PURPOSE: Introspection and discovery of the system's architecture at runtime.
        - CAPABILITIES:
            - get_system_dump(): Full inventory of active Tools, Domains and Plugins.
            - get_domain_metadata(): Detailed analysis of models and schemas.
```

### 🔧 Tool: `auth` (Status: ✅)
```text
Authentication Tool (auth):
        - PURPOSE: Manage system security, password hashing, and JWT token lifecycle.
        - CAPABILITIES:
            - hash_password(password: str) -> str: Securely hashes a plain-text password using bcrypt.
            - verify_password(password: str, hashed_password: str) -> bool: Verifies if a password matches its hash.
            - create_token(data: dict, expires_delta: Optional[int] = None) -> str: 
                Generates a JWT signed token. 'data' should contain claims (e.g. {'sub': user_id}). 
                'expires_delta' is optional minutes until expiration.
            - decode_token(token: str) -> dict: 
                Verifies and decodes a JWT token. Returns the payload dictionary. 
                Raises Exception if token is expired or invalid.
```

### 🔧 Tool: `db` (Status: ✅)
```text
Async PostgreSQL Persistence Tool (db):
        - PURPOSE: Production-grade relational data storage using PostgreSQL with connection pooling.
        - PLACEHOLDERS: Use $1, $2, $3... (NOT '?' like SQLite).
        - CAPABILITIES:
            - await query(sql, params?) → list[dict]: Read multiple rows (SELECT).
            - await query_one(sql, params?) → dict | None: Read a single row (SELECT).
            - await execute(sql, params?) → int | None: Write data (INSERT/UPDATE/DELETE).
              With RETURNING: returns the first column value. Without: returns affected row count.
            - await execute_many(sql, params_list) → None: Batch writes with optimized pipeline.
            - async with transaction() as tx: Explicit transaction block with auto-commit/rollback.
              Inside tx: tx.query(), tx.query_one(), tx.execute() — same signatures.
            - await health_check() → bool: Verify database connectivity.
        - EXCEPTIONS: Raises DatabaseError or DatabaseConnectionError on failure.
```

## 📦 Domain Models
Read the models folder for the domain you are working on before implementing a plugin.

- `ping` → `domains/ping/models/`
- `users` → `domains/users/models/`
