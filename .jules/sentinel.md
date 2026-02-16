## 2025-05-23 - Leaky Error Handling in Framework Core
**Vulnerability:** `HttpServerTool` was catching exceptions and returning `str(e)` directly to the client, potentially exposing stack traces or internal logic (e.g., database constraints).
**Learning:** Framework tools often default to "debug mode" behavior (verbose errors) if not explicitly hardened for production. In MicroCoreOS, tools serve as infrastructure for many plugins, so a vulnerability here affects the entire system.
**Prevention:** Enforce generic error messages at the tool/framework level (middleware or wrapper), ensuring that no plugin can accidentally leak internals via unhandled exceptions.

## 2026-02-16 - Auth Bypass via Parameter Pollution
**Vulnerability:** `HttpServerTool` merged `_auth` data from `request.state` into the request payload *before* merging the request body. This allowed attackers to overwrite the trusted `_auth` object by including an `_auth` key in their JSON body.
**Learning:** Order of operations in data merging is critical for security. Trust boundaries must be enforced by ensuring trusted data (from middleware/state) always overwrites or takes precedence over untrusted user input.
**Prevention:** Always merge trusted context data *last* in the processing pipeline, or use a separate namespace/object for trusted data that cannot be mutated by user input.
