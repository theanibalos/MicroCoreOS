from core.base_plugin import BasePlugin

class TestLogPlugin(BasePlugin):
    def execute(self, message="Hola Mundo"):
        # Recuperamos la tool del container que inyectó el kernel
        logger = self.container.get("logger")
        
        # Usamos la tool
        logger.info(f"Ejecutando plugin de prueba con mensaje: {message}")
        
        return {"status": "success"}