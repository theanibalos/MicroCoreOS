from core.base_tool import BaseTool
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import threading
import asyncio

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
        - add_endpoint(path, method, handler): Registra una nueva URL.
        - El 'handler' debe recibir un diccionario 'data'.
        """

    def add_endpoint(self, path, method, handler):
        async def fastapi_wrapper(request: Request):
            # Extraer datos de Query Params
            data = dict(request.query_params)
            
            # Intentar extraer datos de JSON body
            try:
                body = await request.json()
                if isinstance(body, dict):
                    data.update(body)
            except Exception:
                pass
            
            try:
                # Ejecutamos el plugin pasando los datos como un único argumento 'data'
                result = handler(data) 
                return result
            except Exception as e:
                print(f"[HttpServer] 💥 Error en ruta {path}: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": str(e)}
                )

        self.app.add_api_route(
            path, 
            fastapi_wrapper, 
            methods=[method.upper()]
        )

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