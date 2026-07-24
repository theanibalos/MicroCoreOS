# HTTP Server — Elastic Monolith Gateway

> The HTTP gateway is the entrance to the system. It handles REST, WebSockets, and SSE.
> It is designed for maximum security and transparency.

---

## Security Hardening (Default-On)

MicroCoreOS applies strict security policies to protect domains from common web vulnerabilities.

### 1. Secure Cookies
All cookies set via `context.set_cookie()` have safe defaults:
- **`Secure=True`**: Only sent over HTTPS.
- **`HttpOnly=True`**: Invisible to JavaScript (prevents XSS data theft).
- **`SameSite=Lax`**: Prevents basic cross-site request forgery.

### 2. CSRF Guard
The gateway implements a modern CSRF protection mechanism for mutation methods (`POST`, `PUT`, `DELETE`, `PATCH`):
- If authentication is done via **Cookies** (`access_token`), the client MUST send the `X-Requested-With` header.
- If authentication is done via **Bearer Token** (Authorization header), no extra guard is needed as it is immune to CSRF.

### 3. Swagger UI Lock Icon
Any endpoint registered with `auth_validator` gets a documentation-only `HTTPBearer` dependency
attached to it. This is what makes Swagger UI (`/docs`) show a lock icon on the route and lets you
click **Authorize** once, paste a Bearer token, and have it applied to every "Try it out" call —
without that, protected routes are indistinguishable from public ones in the docs and there's no
way to attach a token from the UI. `auto_error=False` keeps this dependency purely cosmetic: it
never rejects a request on its own — the real check still happens in `_process_request` via the
`auth_validator` you passed to `add_endpoint`/`add_sse_endpoint`.

---

## The Request Pipeline

When a request hits the gateway:
1. **Assembly**: Path, Query, and Body params are merged into a single `data` dictionary.
2. **Causality**: A unique `request_id` is assigned (or honored from `X-Request-ID` header) and set in `current_event_id_var`.
3. **Identity**: The plugin handler's name is set in `current_identity_var` for log attribution.
4. **Authentication**: If `auth_validator` was provided to `add_endpoint`, the token is extracted and validated. On failure, returns HTTP 401. On success, the payload is injected into `data["_auth"]`.
5. **Dispatch**: The handler is executed.

> Note: If a `request_model` is provided, FastAPI validates the request body **before** this pipeline runs (step 0). Validation errors return HTTP 422 automatically.

---

## Automatic Route Sorting

FastAPI and other frameworks often have issues when a parameterized route (like `/users/{id}`) "shadows" a static route (like `/users/me`). 

The HTTP tool automatically sorts all endpoints before registration:
- **Static paths** (no `{}`) are registered first.
- **Parameterized paths** are registered last.

This means you can define your plugins in any order, and `/users/me` will always work correctly without being intercepted by `/users/{id}`.

---

## Implementation Patterns

### REST Endpoints
```python
async def on_boot(self):
    self.http.add_endpoint(
        path="/profiles/{id}",
        method="GET",
        handler=self.get_profile,
        response_model=ProfileResponse
    )

async def get_profile(self, data: dict, context: HttpContext):
    user_id = data["id"]
    # Logic...
    return {"success": True, "data": {...}}
```

### Response Manipulation (`HttpContext`)
The `context` object allows controlling the raw HTTP response:
- `context.set_status(201)`: Change status code. If never called, the default
  is 200 for `success: true` and **400 for `success: false`** — a business
  error that never picks a more specific code (404, 409, 403...) still gets a
  real 4xx, never a bare 200. Call `set_status()` explicitly whenever a more
  precise code applies; it always wins over the default.
- `context.set_header("X-App", "Core")`: Add custom header.
- `context.set_cookie("access_token", value, max_age=3600)`: Set a secure cookie (`HttpOnly=True`, `Secure=True`, `SameSite=Lax` by default).
- `context.redirect("/dashboard", status=302)`: Redirect the browser. The handler's return value is ignored.
- `context.set_binary_response(bytes, "image/png")`: Return non-JSON data. The handler's return value is ignored.

---

## Response Contract

Every endpoint (unless binary) MUST return a JSON envelope:
- **Success**: `{"success": True, "data": {...}}` — HTTP 200 by default.
- **Error**: `{"success": False, "error": "Reason"}` — HTTP 400 by default,
  or whatever `context.set_status()` set explicitly (404, 409, 403...).

The tool automatically catches unhandled exceptions and returns a consistent `500 Internal server error` to the client while logging the real cause server-side.
