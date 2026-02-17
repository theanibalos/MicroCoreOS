## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2025-05-23 - Critical Authorization Bypass in User Management
**Vulnerability:** `DeleteUserPlugin` lacked authentication and authorization checks, allowing any caller to delete any user account via `DELETE /users/delete`.
**Learning:** In the MicroCoreOS architecture, plugins are responsible for their own security logic. The `HttpServerTool` provides guards, but they must be explicitly applied. Defaulting to open endpoints is risky.
**Prevention:** Always verify `_auth` data in plugin `execute` methods for protected resources. Use `security_guard` when registering endpoints.
