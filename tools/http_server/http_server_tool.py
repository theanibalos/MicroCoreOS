from core.base_tool import BaseTool
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
import threading
import asyncio
from fastapi.staticfiles import StaticFiles

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroCoreOS Gateway")
        self._endpoints = []

    @property
    def name(self) -> str:
        return "http_server"

    def setup(self):
        """Configuración inicial del servidor."""
        print("[HttpServer] Configurando FastAPI...")
        
        @self.app.get("/health")
        async def health():
            return {"status": "ok", "tools": "active", "engine": "fastapi"}

    def get_interface_description(self) -> str:
        return """
        Herramienta HTTP Server (FastAPI):
        - add_endpoint(path, method, handler, tags=None, request_model=None, response_model=None): 
          Registra una nueva URL. Soporta Schemas Pydantic para autogenerar Swagger.
        - mount_static(path, directory): Sirve archivos estáticos.
        - add_ws_endpoint(path, handler): Registra un endpoint WebSocket.
        - El 'handler' debe recibir un diccionario 'data'.
        """

    def add_endpoint(self, path, method, handler, tags=None, request_model=None, response_model=None):
        """
        Registra un endpoint con soporte opcional para Schemas (Pydantic).
        - request_model: Clase Pydantic para validar el body y mostrar schema en Swagger.
        - response_model: Clase Pydantic para el formato de respuesta.
        """
        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"

        # Creamos el wrapper con la firma adecuada para que FastAPI genere el Schema
        if request_model:
            async def fastapi_wrapper(request: Request, body: request_model):
                data = dict(request.query_params)
                # Unimos query params con el body validado
                input_data = body.dict() if hasattr(body, "dict") else body
                data.update(input_data)
                
                try:
                    return handler(data)
                except Exception as e:
                    print(f"[HttpServer] 💥 Error en ruta {path}: {e}")
                    return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
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
                    return handler(data)
                except Exception as e:
                    print(f"[HttpServer] 💥 Error en ruta {path}: {e}")
                    return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

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
        """Monta un directorio para servir archivos estáticos."""
        print(f"[HttpServer] Montando estáticos: {path} -> {directory_path}")
        self.app.mount(path, StaticFiles(directory=directory_path), name=path.replace("/", "_"))

    def add_ws_endpoint(self, path, on_connect, on_disconnect=None):
        """
        Registra un endpoint WebSocket.
        - on_connect(websocket): Callback al conectar, debe manejar el loop de recepción.
        - on_disconnect(websocket): Callback opcional al desconectar.
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
                print(f"[HttpServer] WebSocket error en {path}: {e}")
        print(f"[HttpServer] WebSocket registrado: {path}")

    def on_boot_complete(self, container):
        """Arranca el servidor en un hilo separado."""
        def run():
            uvicorn.run(self.app, host="0.0.0.0", port=5000, log_level="warning")

        server_thread = threading.Thread(target=run, daemon=True)
        server_thread.start()
        print(f"[HttpServer] Servidor FastAPI activo en http://localhost:5000")

    def shutdown(self):
        """Cierre limpio del servidor HTTP"""
        print("[HttpServer] Deteniendo servidor (vía Thread termination)...")
        # Uvicorn no tiene un stop() trivial desde hilos externos sin usar señales o Server class
        # Al ser daemon thread, se cerrará con el proceso principal.