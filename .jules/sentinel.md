## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2026-02-10 - Stored XSS in Dashboard
**Vulnerability:** Found Stored XSS in `index.html` and `infra.html` due to unsafe `innerHTML` usage with unvalidated user input (log messages and event payloads).
**Learning:** Even internal dashboards can be attack vectors if they render untrusted data from plugins. The "MicroCoreOS" architecture's event bus propagates data widely, making XSS impact higher.
**Prevention:** Always use `textContent` or `document.createElement` when rendering dynamic data, especially in visualization components like dashboards and tickers.
