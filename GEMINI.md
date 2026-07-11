# MicroCoreOS — Foundational Architecture, Mandates & AI Instructions

This file contains the "Laws of the Kernel" and the specific instructions for AI agents working in this codebase. All development, whether by human or AI, must strictly adhere to these principles to maintain the integrity of the Elastic Monolith.

## 📖 Reading Path (minimize token usage)

**To write a plugin or domain**: Read `AI_CONTEXT.md` + the entity model in `domains/{domain}/models/`. Nothing else.
**For testing, observability, or creating tools**: Read `INSTRUCTIONS_FOR_AI.md`.

## 💻 Commands

```bash
uv run main.py                              # Run the app (also regenerates AI_CONTEXT.md)
uv run pytest                               # Run all tests
uv run pytest tests/test_file.py            # Run single test
docker compose -f dev_infra/docker-compose.yml up -d  # Start dev infrastructure (PostgreSQL)
```

## 🛠️ Essential Rules for AI

1. **Never modify `main.py`** — Kernel auto-discovers everything. Features NEVER touch it.
2. **1 file = 1 feature** — Plugins live in `domains/{domain}/plugins/{feature}_plugin.py`.
3. **DI by parameter name** — `__init__(self, http, db, logger)` injects the tools named `http`, `db`, `logger`.
4. **Entity in models/ = DB mirror only** — Request AND response schemas go inline in the plugin.
5. **No cross-domain imports** — Domains communicate only through `event_bus`.
6. **Return envelope** — Always `{"success": bool, "data": ..., "error": ...}`.
7. **Placeholders** — Always `$1, $2, $3...` in SQL (PostgreSQL-style; SQLite converts internally).
8. **Runner**: Always `uv run`.
9. **Core uses `print()`, not the logger** — Core must not depend on the swappable logging tool.
10. **Protect endpoints**: Pass `auth_validator=self.auth.validate_token` to `add_endpoint` for non-public endpoints, and check ownership via `data["_auth"]["sub"]` inside the handler.

## ⚖️ The "No Hidden Magic" Rule (Kernel Level)

The Kernel (including `ToolProxy` and `Container`) must remain **infrastructure-blind** and **logic-free**.

1.  **NO Kernel Retries**: The `ToolProxy` is forbidden from automatically retrying failed tool calls. Automatic, blind retries at the kernel level lead to non-idempotent operation duplicates (e.g., double payments, duplicate database records).
2.  **Explicit Resilience**: Responsibility for resilience and idempotency is shifted to the appropriate layers:
    *   **Tool Level**: Infrastructure-specific resilience (e.g., a DB Tool handling its own connection pool or local locks).
    *   **Plugin Level**: Business-specific resilience (e.g., a Plugin deciding whether to retry a failed operation based on context).
3.  **Observability over Repair**: The `ToolProxy`'s primary duty is to **observe and report**. It marks tools as `DEAD` on failure and restores them to `OK` only upon successful recovery.

## 📣 Event Bus Mandates

The Event Bus is the nervous system of the project. Its contract is sacred.

1.  **Frozen Contract**: Messages travel in `EventEnvelope` objects. The envelope is frozen to guarantee traceability.
2.  **Broker-Grade Capabilities**: Use the built-in TTL, Retries, and DLQ features of the `EventBusTool` instead of manual implementations.
3.  **Decoupled Publication**: The `publish()` call is strictly fire-and-forget. The publisher must never know or care about who receives the message or when it is delivered.
4.  **Inverted Driver**: Drivers are simple transporters. All logic (Retries, TTL, DLQ, Traceability) is centralized in the Bus.

## 🛡️ Security & Integrity

1.  **Safe Error Reporting**: Never return raw exception strings (`str(e)`) to the client. This prevents leakage of internal details like database schema, file paths, or third-party API keys.
    *   **External**: Return generic messages ("Database error") or business codes ("USER_NOT_FOUND").
    *   **Internal**: Log the full exception for debugging.
2.  **Idempotency by Design**: All mutating operations (POST/PUT/DELETE) should be designed as idempotent whenever possible. Leverage `EventEnvelope.id` for events and unique constraints for the database.
3.  **Stateless JWT Logout**: By default, logout only clears the client-side cookie. The JWT remains valid until expiration. For critical revocation, implement a denylist in the `state` tool or a database table.
