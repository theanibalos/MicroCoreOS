import os
import uvicorn
import threading
from typing import Optional, Dict, Any
from core.base_tool import BaseTool
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

load_dotenv()

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroCoreOS Gateway")
        self._endpoints = []
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
          Registers a new URL. Supports Pydantic Schemas and generic Safety Guards.
        - mount_static(path, directory): Serves static files.
        - add_ws_endpoint(path, handler): Registers a WebSocket endpoint.
        """

    # --- Router Capability ---
    def add_endpoint(self, path, method, handler, tags=None, request_model=None, response_model=None, security_guard=None):
        """
        Registers an endpoint with optional Schema support and a generic Security Guard.
        """
        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"

        # Combine processing logic
        async def process_request(request: Request, body_data: Any):
            data = dict(request.query_params)
            
            # Simple check in the Request State
            if hasattr(request.state, "_auth"):
                data["_auth"] = request.state._auth

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
                return await run_in_threadpool(handler, data)
            except Exception as e:
                print(f"[HttpServer] 💥 Error in route {path}: {e}")
                # SECURITY: Return generic error to client to prevent info leakage
                return JSONResponse(status_code=500, content={"success": False, "error": "Internal Server Error"})

        # Dynamically build the wrapper based on request_model
        # Much simpler now because identity is handled via 'dependencies' in add_api_route
        if request_model:
            if method.upper() == "GET":
                async def wrapper(request: Request, params: request_model = Depends()):
                    return await process_request(request, params)
            else:
                async def wrapper(request: Request, body: request_model = None):
                    return await process_request(request, body)
        else:
            async def wrapper(request: Request):
                return await process_request(request, None)

        wrapper.__name__ = operation_id
        
        # We pass the guard in the dependencies list
        dependencies = [security_guard] if security_guard else []

        self.app.add_api_route(
            path, 
            wrapper, 
            methods=[method.upper()],
            tags=tags or ["Default"],
            response_model=response_model,
            operation_id=operation_id,
            name=operation_id,
            dependencies=dependencies
        )

    def mount_static(self, path, directory_path):
        """Mounts a static files directory."""
        if os.path.exists(directory_path):
            self.app.mount(path, StaticFiles(directory=directory_path), name=path)
            print(f"[HttpServer] Mounting static files: {path} -> {directory_path}")
        else:
            print(f"[HttpServer] ⚠️ Static directory not found: {directory_path}")

    def get_bearer_guard(self, decoder_callable):
        """
        Infrastructure utility to create a FastAPI bearer guard.
        It uses the provided decoder_callable to transform a token into an identity.
        """
        async def verify_identity(request: Request, authorization: Optional[str] = Header(None)):
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
            
            token = authorization.split(" ")[1]
            try:
                # Core logic: Delegate decoding to the provided callable
                payload = decoder_callable(token)
                request.state._auth = payload 
                return payload
            except Exception as e:
                # Infrastructure handles the translation of crypto errors to HTTP 401
                raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
            
        return Depends(verify_identity)

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