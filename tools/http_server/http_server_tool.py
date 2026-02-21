import os
import uvicorn
import threading
from typing import Optional, Dict, Any, Callable
from core.base_tool import BaseTool
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

load_dotenv()

class HttpContext:
    """Explicit context for plugins to interact with HTTP infrastructure."""
    def __init__(self, response: Response):
        self._response = response

    def set_cookie(self, key, value, max_age=3600, httponly=True, samesite="lax", secure=False, path="/"):
        self._response.set_cookie(
            key=key, 
            value=value, 
            max_age=max_age, 
            httponly=httponly, 
            samesite=samesite, 
            secure=secure,
            path=path
        )

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroCoreOS Gateway")
        # Port from .env or default to 5000
        self._port = int(os.getenv("HTTP_PORT", 5000))

    @property
    def name(self) -> str:
        # Changed back to 'http' per user feedback for consistency and to avoid breaking old plugins
        return "http"

    def setup(self):
        """Initial server configuration."""
        print(f"[HttpServer] Configuring FastAPI on port {self._port}...")
        
        @self.app.middleware("http")
        async def add_security_headers(request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "tools": "active", "engine": "fastapi"}

    def get_interface_description(self) -> str:
        return """
        HTTP Server Tool (http):
        - add_endpoint(path, method, handler, tags=None, request_model=None, response_model=None, security_guard=None): 
          Registers a path. The handler MUST accept (data: dict, context: HttpContext).
        - HttpContext.set_cookie(key, value, max_age=3600, httponly=True, samesite="lax", secure=False, path="/"): 
          Accessible via the 'context' parameter in the handler.
        - get_bearer_guard(decoder, cookie_name="access_token"): Returns a hybrid guard (supports Header or Cookie).
        - mount_static(path, directory): Serves static files.
        - add_ws_endpoint(path, handler): Registers a WebSocket endpoint.
        """

    # --- Router Capability ---
    def add_endpoint(self, path, method, handler, tags=None, request_model=None, response_model=None, auth_validator=None):
        """
        Registers an endpoint.
        If auth_validator is provided, it will intercept the request, extract the token from headers/cookies,
        validate it, and pass the payload to the handler via data['_auth'].
        """
        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"
        
        # Combine processing logic
        async def process_request(request: Request, response: Response, body_data: Any):
            data = dict(request.query_params)

            if body_data:
                input_body = body_data.dict() if hasattr(body_data, "dict") else body_data
                if isinstance(input_body, dict):
                    data.update(input_body)
            elif request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        data.update(body)
                except Exception: pass

            try:
                # 100% Explicit: Provide a tiny context for the plugin to interact with the world
                context = HttpContext(response)
                
                # Execute Auth Validator if defined
                if auth_validator:
                    token = None
                    auth_header = request.headers.get("Authorization")
                    if auth_header and auth_header.startswith("Bearer "):
                        token = auth_header.split(" ")[1]
                    else:
                        token = request.cookies.get("access_token")
                        
                    if not token:
                        raise HTTPException(status_code=401, detail="Unauthorized: Missing token")
                        
                    # Delega la validación real al la función inyectada (IdentityTool)
                    payload = auth_validator(token)
                    if not payload:
                        raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")
                        
                    data["_auth"] = payload

                # We call the handler with data AND the explicit context
                return await run_in_threadpool(handler, data, context)
            except HTTPException as he:
                raise he
            except Exception as e:
                print(f"[HttpServer] 💥 Error in route {path}: {e}")
                return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

        # Dynamically build the wrapper based on request_model
        if request_model:
            if method.upper() == "GET":
                async def wrapper(request: Request, response: Response, params: request_model = Depends()):
                    return await process_request(request, response, params)
            else:
                async def wrapper(request: Request, response: Response, body: request_model = None):
                    return await process_request(request, response, body)
        else:
            async def wrapper(request: Request, response: Response):
                return await process_request(request, response, None)

        wrapper.__name__ = operation_id

        self.app.add_api_route(
            path, 
            wrapper, 
            methods=[method.upper()],
            tags=tags or ["Default"],
            response_model=response_model,
            operation_id=operation_id,
            name=operation_id
        )

    def mount_static(self, path, directory_path):
        """Mounts a static files directory."""
        if os.path.exists(directory_path):
            self.app.mount(path, StaticFiles(directory=directory_path), name=path)
            print(f"[HttpServer] Mounting static files: {path} -> {directory_path}")
        else:
            print(f"[HttpServer] ⚠️ Static directory not found: {directory_path}")

    def add_ws_endpoint(self, path, on_connect, on_disconnect=None):
        """
        Registers a WebSocket endpoint.
        """
        @self.app.websocket(path)
        async def ws_handler(websocket: WebSocket):
            await websocket.accept()
            try:
                await on_connect(websocket)
            except WebSocketDisconnect:
                if on_disconnect:
                    on_disconnect(websocket)
            except Exception as e:
                print(f"[HttpServer] WebSocket error on {path}: {e}")
        print(f"[HttpServer] WebSocket registered: {path}")

    def on_boot_complete(self, container):
        """Starts the server in a separate thread."""
        def run():
            uvicorn.run(self.app, host="0.0.0.0", port=self._port, log_level="warning")

        server_thread = threading.Thread(target=run, daemon=True)
        server_thread.start()
        print(f"[HttpServer] FastAPI server active at http://localhost:{self._port}")

    def shutdown(self):
        """Clean shutdown of HTTP server"""
        print("[HttpServer] Stopping server (via Thread termination)...")
        # Daemon thread will close with main process.