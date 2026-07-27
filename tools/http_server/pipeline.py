"""
Request processing pipeline for the HTTP Server Tool.

Split out of http_server_tool.py (mechanical move, no behavior change).
_process_request, _sse_response and _extract_bearer_token were previously
HttpServerTool methods; none of them actually depended on other instance
state except self._paused_owners (now an explicit parameter of
_process_request), so they were extracted as free functions instead of
being left behind as artificially-parameterized methods.
"""

import uuid
import inspect
from typing import Optional, Any, Callable
from pydantic import BaseModel
from core.context import current_identity_var, current_event_id_var
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from tools.http_server.context import HttpContext


def _serialize(obj):
    """Recursively convert Pydantic models to dicts so JSONResponse can serialize them."""
    if isinstance(obj, BaseModel):
        return _serialize(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REQUEST PROCESSING PIPELINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _sse_response(request: Request, generator: Callable, auth_validator: Optional[Callable]):
    """Shared SSE request-handling body used by add_sse_endpoint's two wrapper variants."""
    from fastapi.responses import StreamingResponse

    data: dict = {}
    data.update(request.query_params)
    data.update(request.path_params)

    if auth_validator:
        token = _extract_bearer_token(request)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Missing authorization token"},
            )
        if inspect.iscoroutinefunction(auth_validator):
            payload = await auth_validator(token)
        else:
            payload = await run_in_threadpool(auth_validator, token)
        if not payload:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Invalid or expired token"},
            )
        data["_auth"] = payload

    async def event_stream():
        gen = generator(data)
        try:
            async for chunk in gen:
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            await gen.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _process_request(
    request: Request,
    body_data: Any,
    handler: Callable,
    auth_validator: Optional[Callable],
    paused_owners: set,
    files: Optional[list] = None,
) -> Any:
    """
    Core request processing pipeline. Executed for every incoming HTTP request.

    Phases:
        1. Data Assembly   — merge path params + query params + body into one flat dict
        2. Context Seeding — set causality ContextVars (event_id, identity)
        3. Authentication  — validate token if auth_validator is provided → inject into data["_auth"]
        4. Dispatch        — call the plugin handler (async or sync)
        5. Response        — serialize result as JSONResponse with the correct status code
    """
    # ── Phase 1: Data Assembly ─────────────────────────────────────────────
    data: dict = {}
    # 1. Query parameters always come from the request object
    data.update(request.query_params)

    # 2. Path parameters always included
    data.update(request.path_params)

    # 3. Body/Form data
    # If body_data is provided (from FastAPI DI), it contains body/form fields
    if body_data is not None:
        if hasattr(body_data, "model_dump"):
            data.update(body_data.model_dump())
        elif hasattr(body_data, "dict"):
            data.update(body_data.dict())
        elif isinstance(body_data, dict):
            data.update(body_data)
    else:
        # Fallback: manual extraction if no DI model was used
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                raw_json = await request.json()
                if isinstance(raw_json, dict):
                    data.update(raw_json)
            except Exception: pass
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            try:
                form = await request.form()
                for key, value in form.items():
                    if not hasattr(value, "filename"): # Only take non-field data
                        data[key] = value
            except Exception: pass

    if files is not None:
        data["_files"] = files

    # ── Phase 2: Causality Context Seeding ────────────────────────────────
    # Honor X-Request-ID from an upstream MicroCoreOS service if present,
    # so the entire cross-service call chain shares the same root event ID.
    # If absent (first hop or external client), generate a fresh UUID.
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # Same identity scheme as the event bus: prefer the kernel-stamped
    # "domain.ClassName" so emitters and subscribers share one format.
    owner = getattr(handler, "__self__", None)
    if owner is not None:
        base = getattr(owner, "_identity", None) or owner.__class__.__name__
        identity = f"{base}.{handler.__name__}"
    else:
        identity = getattr(handler, "__name__", "unknown")
    id_token = current_event_id_var.set(request_id)
    ident_token = current_identity_var.set(identity)
    print(
        f"[HttpServer] → {request.method} {request.url.path}"
        f"  req={request_id[:8]}  identity={identity}"
    )

    try:
        # Chaos/ops pause (Issue 34): the paused owner's endpoints answer
        # 503 before auth or dispatch — simulates the service being down.
        if any(identity == p or identity.startswith(p + ".")
               for p in paused_owners):
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": "Service temporarily unavailable (paused)"},
            )

        context = HttpContext()

        # ── Phase 3: Authentication ────────────────────────────────────────
        if auth_validator:
            token = _extract_bearer_token(request)
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "Missing authorization token"},
                )
            if inspect.iscoroutinefunction(auth_validator):
                payload = await auth_validator(token)
            else:
                payload = await run_in_threadpool(auth_validator, token)

            if not payload:
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "Invalid or expired token"},
                )
            data["_auth"] = payload

        # ── Phase 4: Handler Dispatch ──────────────────────────────────────
        if inspect.iscoroutinefunction(handler):
            result = await handler(data, context)
        else:
            result = await run_in_threadpool(handler, data, context)

        status_code = context.status_code
        if not context._status_explicit and isinstance(result, dict) and result.get("success") is False:
            status_code = 400

        print(
            f"[HttpServer] ← {request.method} {request.url.path}"
            f"  req={request_id[:8]}  status={status_code}"
        )

        # ── Phase 5: Response ──────────────────────────────────────────────
        if context.redirect_url:
            from fastapi.responses import RedirectResponse
            redirect_response = RedirectResponse(
                url=context.redirect_url, status_code=context.status_code
            )
            for key, value in context._headers.items():
                redirect_response.headers[key] = value
            for cookie in context._cookies:
                redirect_response.set_cookie(**cookie)
            return redirect_response

        binary = context.binary_content
        if binary:
            from fastapi.responses import Response
            content, media_type = binary
            response = Response(content=content, media_type=media_type, status_code=context.status_code)
            context.apply_to(response)
            return response

        json_response = JSONResponse(status_code=status_code, content=_serialize(result))
        context.apply_to(json_response)
        return json_response

    except Exception as e:
        # Unhandled exception: log the real error server-side, return generic message to client.
        print(f"[HttpServer] 💥 Unhandled exception in '{identity}': {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error"},
        )
    finally:
        current_identity_var.reset(ident_token)
        current_event_id_var.reset(id_token)


# ── Utilities ────────────────────────────────────────────────────────────────

def _extract_bearer_token(request: Request) -> Optional[str]:
    """
    Extracts the Bearer token from the request.
    Priority:
      1. Authorization header (Bearer) -> Preferred for Apps/CLI, immune to CSRF.
      2. access_token cookie -> Subject to CSRF, requires X-Requested-With guard.
    """
    # 1. Bearer Token (Highest security, default for non-browser clients)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 2. Cookie Auth (Web clients)
    token = request.cookies.get("access_token")
    if token:
        # CSRF Guard: If it's a mutation method (POST/PUT/DELETE) and we are
        # using cookies, we MUST verify the request was initiated by our own
        # JavaScript. An attacker-controlled form cannot add custom headers.
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not request.headers.get("X-Requested-With"):
                print(f"[HttpServer] 🛡️ CSRF block: Mutation {request.method} "
                      f"via cookie missing X-Requested-With header.")
                return None
        return token

    return None
