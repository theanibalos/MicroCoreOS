# MicroCoreOS — Foundational Architecture & Mandates

This file contains the "Laws of the Kernel". All development, whether by human or AI, must strictly adhere to these principles to maintain the integrity of the Elastic Monolith.

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
