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
Automatically generates the AI_CONTEXT.md manifest that serves as a technical manual for AI.
```

### 🔧 Tool: `event_bus` (Status: ✅)
```text
Event Bus Tool (event_bus):
        - PURPOSE: Orchestrate asynchronous communication between isolated domains.
        - IDEAL FOR: Side effects (notifications, logs) and cross-domain RPC requests.
        - CAPABILITIES:
            - publish(name, data): Fire and forget event. 
            - subscribe(name, callback): Listens for events. Callback receives {_event_name, payload}.
            - request(name, data, timeout=5): Synchronous Request-Response (RPC) over events.
```

### 🔧 Tool: `http` (Status: ✅)
```text
HTTP Server Tool (http):
        - PURPOSE: Expose business logic as a RESTful API and serve Web content.
        - CAPABILITIES:
            - add_endpoint(path, method, handler, ...): Registers a new route.
            - mount_static(path, directory): Serves frontend files (SPA, dashboards).
            - add_ws_endpoint(path, handler): Enables real-time WebSocket communication.
            - HttpContext.set_cookie(...): Advanced cookie management.
```

### 🔧 Tool: `logger` (Status: ✅)
```text
Logging Tool (logger):
        - PURPOSE: Record system events and business activity for audit and debugging.
        - CAPABILITIES:
            - info(message): General information.
            - error(message): Critical failures.
            - warning(message): Non-critical alerts.
        - NOTE: All logs are automatically mirrored to the Event Bus ('system.log').
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

### 🔧 Tool: `identity` (Status: ✅)
```text
Identity & Security Tool (identity):
        - PURPOSE: Cryptographic services for Authentication and Authorization.
        - CAPABILITIES:
            - hash_password(password): Secure password hashing (Bcrypt).
            - verify_password(password, hashed): Fast password verification.
            - generate_token(data, expires_delta=None): JWT creation.
            - decode_token(token): JWT validation and decoding.
```

### 🔧 Tool: `db` (Status: ✅)
```text
SQLite Persistence Tool (db):
        - PURPOSE: Persistent relational data storage using SQL.
        - IDEAL FOR: Domain entities (Users, Products), relational queries, and ACID transactions.
        - CAPABILITIES:
            - query(sql, params): Read data (SELECT). Returns list of tuples.
            - execute(sql, params): Write data (INSERT, UPDATE, DELETE). Returns last ID.
```

## 📦 Domain Models
Active data structures. Use these in `request_model`/`response_model`.

### 🧩 Domain `products`
- Model: `products_model.py`

### 🧩 Domain `users`
- Model: `user_model.py`

