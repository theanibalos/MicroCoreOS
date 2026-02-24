# 📜 SYSTEM MANIFEST

> **NOTICE:** This is a LIVE inventory. For implementation guides, read [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).

## 🏗️ Quick Architecture Ref
- **Pattern**: `__init__` (DI) -> `on_boot` (Reg) -> `execute` (Action).
- **Injection**: Tools are injected by name in the constructor.

## 🛠️ Available Tools
Check method signatures before implementation.

### 🔧 Tool: `config` (Status: ✅)
```text
Configuration Tool (config):
        - PURPOSE: Centralized access to environment variables and system settings.
        - CAPABILITIES:
            - get(key, default=None): Gets a configuration value.
```

### 🔧 Tool: `context_manager` (Status: ✅)
```text
Context Manager Tool (context_manager):
        - PURPOSE: Automatically manages and generates live AI contextual documentation.
        - CAPABILITIES:
            - Reads the system registry.
            - Exports active tools, health status, and domain models to AI_CONTEXT.md.
```

### 🔧 Tool: `event_bus` (Status: ✅)
```text
Async Event Bus Tool (event_bus):
        - PURPOSE: High-performance, non-blocking communication between plugins using Pub/Sub and Async RPC.
        - CAPABILITIES:
            - await publish(event_name, data): Broadcasts an event. Fire-and-forget.
            - await subscribe(event_name, callback): Listens for a specific event. Callback can be async or sync.
            - await request(event_name, data, timeout=5): Performs an Asynchronous RPC. Waits for a response from a subscriber.
        - TRACING: Tracks event causality across the system for observability.
```

### 🔧 Tool: `http` (Status: ✅)
```text
Hybrid HTTP Server Tool (http):
        - PURPOSE: Provides a FastAPI-powered HTTP gateway that supports both sync and async handlers.
        - CAPABILITIES:
            - add_endpoint(path, method, handler, tags=None, request_model=None, response_model=None, auth_validator=None): 
                Registers a new route.
                - tags: List of strings for OpenAPI documentation.
                - request_model: Pydantic class for validation and body parsing.
                - response_model: Pydantic class for standardized response shapes.
                - auth_validator: A function (sync or async) that takes a token and returns a payload or None.
            - mount_static(path, directory_path): Serves static files from a directory.
            - add_ws_endpoint(path, on_connect, on_disconnect=None): Registers a WebSocket handler.
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

### 🔧 Tool: `db` (Status: ✅)
```text
Async SQLite Persistence Tool (db):
        - PURPOSE: Persistent relational data storage using SQL (Asynchronous).
        - CAPABILITIES:
            - await query(sql, params): Read data (SELECT). Returns list of rows.
            - await execute(sql, params): Write data (INSERT, UPDATE, DELETE). Returns last ID.
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

## 📦 Domain Models
Active data structures. Use these in `request_model`/`response_model`.

### 🧩 Domain `ping`
- Model: `ping_model.py`

### 🧩 Domain `users`
- Model: `auth.py`
- Model: `user.py`

