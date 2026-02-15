## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2025-05-23 - Auth Bypass via Parameter Pollution
**Vulnerability:** The `HttpServerTool` merged request body data into the request data dictionary *after* setting the `_auth` information. This allowed an attacker to overwrite the trusted `_auth` object by sending an `_auth` field in the JSON body, potentially leading to privilege escalation or identity spoofing.
**Learning:** Order of operations in request processing middleware is critical. Trusted data (like authentication context) must always be applied *after* untrusted user input (body/query params) to prevent overwrites.
**Prevention:** Always sanitize and prioritize trusted context data over user input. In framework code, ensure that the final state of the request object reflects the system's truth, not the user's input.
