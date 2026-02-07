## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2025-05-24 - DOM-Based XSS in Dashboard
**Vulnerability:** The system dashboard used `innerHTML` to render log messages and event data from the `EventBus`. Malicious payloads in logs (e.g., from user input) were executed in the admin's browser.
**Learning:** Even "internal" dashboards are high-risk targets for XSS if they display data derived from public inputs (logs, user names). Trusting "system" events is a dangerous assumption.
**Prevention:** Always use `textContent` or robust DOM creation methods for dynamic data, even in internal tools. Never use `innerHTML` for displaying event payloads or logs.
