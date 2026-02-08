## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2026-02-08 - Content Security Policy & Frontend Separation
**Vulnerability:** Inline scripts and styles in the frontend forced the use of `'unsafe-inline'` in CSP, allowing potential XSS vulnerabilities.
**Learning:** `MicroCoreOS` frontend files (`index.html`, `infra.html`) contained substantial inline logic and styling, making CSP enforcement impossible without refactoring.
**Prevention:** Separate all CSS and JavaScript into dedicated files (`.css`, `.js`) and update the `HttpServerTool` CSP middleware to remove `'unsafe-inline'`, enforcing strict content security by default.
