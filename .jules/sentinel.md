## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2025-05-23 - Broken Access Control in UpdateUserPlugin
**Vulnerability:** `UpdateUserPlugin` allowed any user (or unauthenticated request) to update any user profile by simply providing the `id` in the payload. It lacked authentication and authorization checks.
**Learning:** Plugins in MicroCoreOS are independent and must explicitly request security guards and implement authorization logic. The "blind kernel" does not enforce security by default.
**Prevention:** Always use `security_guard` in `add_endpoint` for sensitive routes. Inside `execute`, validate `_auth` data against the target resource ID (IDOR check).
