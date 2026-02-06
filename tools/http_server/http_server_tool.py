from core.base_tool import BaseTool
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
import threading
import asyncio
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroCoreOS Gateway")
        self._endpoints = []

    @property
    def name(self) -> str:
        return "http_server"

    def setup(self):
        """Initial server configuration."""
        print("[HttpServer] Configuring FastAPI...")
        
        @self.app.middleware("http")
        async def add_security_headers(request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "default-src 'self'"
            return response

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "tools": "active", "engine": "fastapi"}

    def get_interface_description(self) -> str:
        return """
        HTTP Server Tool (FastAPI):
        - add_endpoint(path, method, handler, tags=None, request_model=None, response_model=None): 
          Registers a new URL. Supports Pydantic Schemas for auto-generated Swagger.
        - mount_static(path, directory): Serves static files.
        - add_ws_endpoint(path, handler): Registers a WebSocket endpoint.
        - The 'handler' must receive a 'data' dictionary.
        """

    def add_endpoint(self, path, method, handler, tags=None, request_model=None, response_model=None):
        """
        Registers an endpoint with optional Schema support (Pydantic).
        - request_model: Pydantic class to validate body and show schema in Swagger.
        - response_model: Pydantic class for response format.
        """
        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"

        # Create wrapper with appropriate signature for FastAPI Schema generation
        if request_model:
            def fastapi_wrapper(request: Request, body: request_model):
                data = dict(request.query_params)
                # Merge query params with validated body
                input_data = body.dict() if hasattr(body, "dict") else body
                data.update(input_data)
                
                try:
                    return handler(data)
                except Exception as e:
                    print(f"[HttpServer] 💥 Error in route {path}: {e}")
                    return JSONResponse(status_code=500, content={"success": False, "error": "Internal Server Error"})
        else:
            async def fastapi_wrapper(request: Request):
                data = dict(request.query_params)
                try:
                    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                        body = await request.json()
                        if isinstance(body, dict):
                            data.update(body)
                except Exception: pass
                
                try:

                    return await run_in_threadpool(handler, data)
                except Exception as e:
                    print(f"[HttpServer] 💥 Error in route {path}: {e}")
                    return JSONResponse(status_code=500, content={"success": False, "error": "Internal Server Error"})

        fastapi_wrapper.__name__ = operation_id

        self.app.add_api_route(
            path, 
            fastapi_wrapper, 
            methods=[method.upper()],
            tags=tags or ["Default"],
            response_model=response_model,
            operation_id=operation_id,
            name=operation_id
        )

    def mount_static(self, path, directory_path):
        """Mounts a directory to serve static files."""
        print(f"[HttpServer] Mounting static files: {path} -> {directory_path}")
        self.app.mount(path, StaticFiles(directory=directory_path), name=path.replace("/", "_"))

    def add_ws_endpoint(self, path, on_connect, on_disconnect=None):
        """
        Registers a WebSocket endpoint.
        - on_connect(websocket): Callback on connect, must handle the receive loop.
        - on_disconnect(websocket): Optional callback on disconnect.
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
            uvicorn.run(self.app, host="0.0.0.0", port=5000, log_level="warning")

        server_thread = threading.Thread(target=run, daemon=True)
        server_thread.start()
        print(f"[HttpServer] FastAPI server active at http://localhost:5000")

    def shutdown(self):
        """Clean shutdown of HTTP server"""
        print("[HttpServer] Stopping server (via Thread termination)...")
        # Uvicorn doesn't have a trivial stop() from external threads without signals or Server class
        # Being a daemon thread, it will close with the main process.