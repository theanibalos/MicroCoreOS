from core.base_tool import BaseTool
import datetime

class LoggerTool(BaseTool):
    @property
    def name(self) -> str:
        return "logger"

    def setup(self):
        """Inicialización del logger (en este caso, simple consola)"""
        print("[System] LoggerTool inicializado correctamente.")

    def get_interface_description(self) -> str:
        """
        Este es el manual para la IA.
        """
        return """
        Herramienta de Logs:
        - info(message): Registra información general.
        - error(message): Registra errores críticos.
        - warning(message): Registra advertencias.
        """

    # Métodos funcionales que usará el plugin
    def info(self, message: str):
        print(f"[{datetime.datetime.now()}] [INFO] {message}")

    def error(self, message: str):
        print(f"[{datetime.datetime.now()}] [ERROR] {message}")

    def warning(self, message: str):
        print(f"[{datetime.datetime.now()}] [WARN] {message}")