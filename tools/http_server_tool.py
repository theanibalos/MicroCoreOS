from core.base_tool import BaseTool
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
import threading
import asyncio
from fastapi.staticfiles import StaticFiles

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = FastAPI(title="MicroOS Gateway")
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
        - add_endpoint(path, method, handler, tags=None): Registra una nueva URL con tags opcionales.
        - mount_static(path, directory): Sirve archivos estáticos.
        - add_ws_endpoint(path, handler): Registra un endpoint WebSocket.
        - El 'handler' debe recibir un diccionario 'data'.
        """

    def add_endpoint(self, path, method, handler, tags=None):
        """
        Registra un endpoint con un envoltorio que extrae datos de Query y Body.
        - tags: Lista de strings para agrupar en Swagger (ej: ["Users"])
        """
        # Generar un nombre único para el wrapper interno para evitar colisiones en Swagger
        handler_name = handler.__name__ if hasattr(handler, "__name__") else str(hash(handler))
        operation_id = f"{handler_name}_{method}_{path.replace('/', '_')}"

        async def fastapi_wrapper(request: Request):
            data = dict(request.query_params)
            try:
                if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                    body = await request.json()
                    if isinstance(body, dict):
                        data.update(body)
            except Exception: pass
            
            try:
                result = handler(data) 
                return result
            except Exception as e:
                print(f"[HttpServer] 💥 Error en ruta {path}: {e}")
                return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

        # Renombrar la función dinámicamente para que Swagger la vea diferente
        fastapi_wrapper.__name__ = operation_id

        self.app.add_api_route(
            path, 
            fastapi_wrapper, 
            methods=[method.upper()],
            tags=tags or ["Default"],
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