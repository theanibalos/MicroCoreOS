from core.base_tool import BaseTool
from flask import Flask, request, jsonify
import threading

class HttpServerTool(BaseTool):
    def __init__(self):
        self.app = Flask(__name__)
        self._endpoints = []

    @property
    def name(self) -> str:
        return "http_server"

    def setup(self):
        """Configuración inicial del servidor."""
        print("[HttpServer] Configurando Flask...")
        
        @self.app.route("/health", methods=["GET"])
        def health():
            return {"status": "ok", "tools": "active"}

    def get_interface_description(self) -> str:
        return """
        Herramienta HTTP Server:
        - add_endpoint(path, method, handler): Registra una nueva URL.
        - El 'handler' debe ser una función que reciba datos (dict) y retorne un dict.
        - Los datos se extraen de JSON body o Query Params automáticamente.
        """

    def add_endpoint(self, path, method, handler):
        def flask_wrapper():
            data = request.get_json(silent=True) or {}
            data.update(request.args.to_dict())
            
            try:
                # Intentamos ejecutar el plugin
                # Pasamos 'data' como kwargs para que coincida con def execute(self, **kwargs)
                result = handler(**data) 
                return jsonify(result)
            except Exception as e:
                # AQUÍ capturamos el fallo antes que Flask
                print(f"[HttpServer] 💥 Error controlado en ruta {path}: {e}")
                return jsonify({
                    "success": False, 
                    "error": "Plugin Execution Error",
                    "details": str(e)
                }), 500

        endpoint_name = f"{method}_{path.replace('/', '_')}"
        self.app.add_url_rule(path, endpoint_name, flask_wrapper, methods=[method])

    def on_boot_complete(self, container):
        """Arranca el servidor en un hilo separado al finalizar el boot del Kernel."""
        def run():
            # use_reloader=False es crítico al usar hilos
            self.app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

        server_thread = threading.Thread(target=run, daemon=True)
        server_thread.start()
        print(f"[HttpServer] Servidor HTTP activo en http://localhost:5000")

    def shutdown(self):
        """Cierre limpio del servidor HTTP"""
        print("[HttpServer] Deteniendo servidor...")
        # Flask no tiene un método .stop() sencillo en su servidor de desarrollo, 
        # pero al ser un hilo daemon, el SO lo limpiará si el Kernel cierra bien.
        # Aquí cerraríamos conexiones a sockets o proxies si los hubiera.