import os
import uvicorn
import asyncio
import inspect
from typing import Optional, Dict, Any, Callable
from core.base_tool import BaseTool
from core.context import current_identity_var, current_event_id_var
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

load_dotenv()

class HttpContext:
    def __init__(self, response: Response):
        self._response = response

    def set_cookie(self, key, value, max_age=3600, httponly=True, samesite="lax", secure=False, path="/"):
        self._response.set_cookie(key=key, value=value, max_age=max_age, httponly=httponly, samesite=samesite, secure=secure, path=path)

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroCoreOS Gateway")
        self._port = int(os.getenv("HTTP_PORT", 5000))
        self._server = None
        self._endpoints = []

    @property
    def name(self) -> str:
        return "http"

    async def setup(self):
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
        Hybrid HTTP Server Tool (http):
        - PURPOSE: Provides a FastAPI-powered HTTP gateway that supports both sync and async handlers.
        - CAPABILITIES:
            - add_endpoint(path, method, handler, tags=None, request_model=None, response_model=None, auth_validator=None): 
                Registers a new route.
                - tags: List of strings for OpenAPI documentation.
                - request_model: Pydantic class for validation and body parsing.
                - response_model: Pydantic class for standardized response shapes.
                - auth_validator: A function (sync or async) that takes a token and returns a payload or None.
            - mount_static(path, directory_path): Serves static files from a directory.
            - add_ws_endpoint(path, on_connect, on_disconnect=None): Registers a WebSocket handler.
        """

    def add_endpoint(self, path, method, handler, tags=None, request_model=None, response_model=None, auth_validator=None):
        self._endpoints.append({
            "path": path,
            "method": method,
            "handler": handler,
            "tags": tags,
            "request_model": request_model,
            "response_model": response_model,
            "auth_validator": auth_validator
        })
        
    async def _register_buffered_endpoints(self):
        sorted_endpoints = sorted(self._endpoints, key=lambda x: ("{" in x["path"], x["path"]))
        for ep in sorted_endpoints:
            self._apply_endpoint(ep)

    def _apply_endpoint(self, ep):
        path = ep["path"]
        method = ep["method"]
        handler = ep["handler"]
        tags = ep["tags"]
        request_model = ep["request_model"]
        response_model = ep["response_model"]
        auth_validator = ep["auth_validator"]

        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"

        async def process_request(request: Request, response: Response, body_data: Any):
            data = dict(request.query_params)
            data.update(request.path_params)
            if body_data:
                input_body = body_data.dict() if hasattr(body_data, "dict") else body_data
                if isinstance(input_body, dict): data.update(input_body)
            elif request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                try:
                    body = await request.json()
                    if isinstance(body, dict): data.update(body)
                except Exception: pass

            try:
                import threading
                import uuid
                thread_name = threading.current_thread().name
                
                # Seed the architectural context for traceability
                request_id = str(uuid.uuid4())
                id_token = current_event_id_var.set(request_id)
                
                # Infer identity from handler object (e.g., PluginClassName.method_name)
                caller_identity = handler_name
                if hasattr(handler, "__self__"):
                    caller_identity = f"{handler.__self__.__class__.__name__}.{handler.__name__}"
                
                ident_token = current_identity_var.set(caller_identity)
                
                print(f"[HttpServer] {method} {path} >> Dispatching (Req: {request_id[:8]}, Identity: {caller_identity})")
                
                try:
                    context = HttpContext(response)
                    
                    # Auth Logic
                    if auth_validator:
                        token = request.headers.get("Authorization", "").split(" ")[1] if request.headers.get("Authorization") else request.cookies.get("access_token")
                        if not token: raise HTTPException(status_code=401, detail="Unauthorized")
                        
                        if inspect.iscoroutinefunction(auth_validator):
                            payload = await auth_validator(token)
                        else:
                            payload = await run_in_threadpool(auth_validator, token)
                        
                        if not payload: raise HTTPException(status_code=401, detail="Unauthorized")
                        data["_auth"] = payload

                    # Handler Logic
                    if inspect.iscoroutinefunction(handler):
                        res = await handler(data, context)
                    else:
                        res = await run_in_threadpool(handler, data, context)
                    
                    print(f"[HttpServer] {method} {path} << Finished (Req: {request_id[:8]})")
                    return res
                finally:
                    current_identity_var.reset(ident_token)
                    current_event_id_var.reset(id_token)

            except HTTPException as he: raise he
            except Exception as e:
                print(f"[HttpServer] 💥 Error in {method} {path}: {e}")
                return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

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
        self.app.add_api_route(path, wrapper, methods=[method.upper()], tags=tags, response_model=response_model, operation_id=operation_id)

    def mount_static(self, path, directory_path):
        if os.path.exists(directory_path):
            self.app.mount(path, StaticFiles(directory=directory_path), name=path)

    def add_ws_endpoint(self, path, on_connect, on_disconnect=None):
        @self.app.websocket(path)
        async def ws_handler(websocket: WebSocket):
            await websocket.accept()
            try:
                if inspect.iscoroutinefunction(on_connect): await on_connect(websocket)
                else: await run_in_threadpool(on_connect, websocket)
            except WebSocketDisconnect:
                if on_disconnect:
                    if inspect.iscoroutinefunction(on_disconnect): await on_disconnect(websocket)
                    else: await run_in_threadpool(on_disconnect, websocket)
            except Exception as e:
                print(f"[HttpServer] WebSocket error on {path}: {e}")

    async def on_boot_complete(self, container):
        await self._register_buffered_endpoints()
        config = uvicorn.Config(self.app, host="0.0.0.0", port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        print(f"[HttpServer] FastAPI server active at http://localhost:{self._port}")

    async def shutdown(self):
        if self._server:
            self._server.should_exit = True
            await asyncio.sleep(0.5)