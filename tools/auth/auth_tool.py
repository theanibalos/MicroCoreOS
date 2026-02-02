from core.base_tool import BaseTool

class AuthTool(BaseTool):
    """
    Herramienta de Autenticación (AuthTool):
    Baseline para validación de tokens/usuarios.
    """

    @property
    def name(self) -> str:
        return "auth"

    def setup(self):
        print("[System] AuthTool: Lista para validación.")

    def get_interface_description(self) -> str:
        return """
        Herramienta de Autenticación (auth):
        - verify_token(token): Verifica si un token es válido (SIMULADO).
        - get_user_from_token(token): Retorna datos del usuario (SIMULADO).
        """

    def verify_token(self, token: str) -> bool:
        """Simulación de verificación de token"""
        # Aquí iría la lógica de JWT
        return token == "secret-token"

    def get_user_from_token(self, token: str) -> dict:
        """Retorna datos simulados si el token es válido"""
        if self.verify_token(token):
            return {"id": 1, "name": "Admin", "role": "admin"}
        return None

    def shutdown(self):
        pass
