from core.base_plugin import BasePlugin

class FailPlugin(BasePlugin):
    def on_boot(self):
        """Registramos la ruta del fallo"""
        http = self.container.get("http_server")
        http.add_endpoint("/test-fail", "GET", self.execute)

    def execute(self, **kwargs):
        # 1. Extracción (Ok)
        # 2. Lógica de Negocio (¡BUM!)
        print("[FailPlugin] Recibida petición, procediendo a explotar...")
        numero_mágico = 100 / 0 
        
        return {"resultado": numero_mágico}