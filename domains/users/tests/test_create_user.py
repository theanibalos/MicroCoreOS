import unittest
import sys
import os
from unittest.mock import MagicMock

# Añadir el raíz del proyecto al path para que encuentre 'domains'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from domains.users.plugins.create_user_plugin import CreateUserPlugin
from domains.users.models.user_model import UserModel

class TestCreateUserPlugin(unittest.TestCase):
    """
    PRUEBA DE AISLAMIENTO REAL (Unit Test)
    Demuestra que el plugin puede vivir solo con mocks,
    sin base de datos real, sin servidor y sin kernel.
    """
    
    def setUp(self):
        # 1. Creamos Mocks de las herramientas que pide el constructor
        # self.http, self.db, self.logger, self.event_bus
        self.mock_http = MagicMock()
        self.mock_identity = MagicMock() # Added mock for identity
        self.mock_db = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_bus = MagicMock()
        
        # 2. Instanciamos el plugin REAL
        self.plugin = CreateUserPlugin(
            http=self.mock_http,
            identity=self.mock_identity, # Injected identity mock
            db=self.mock_db,
            logger=self.mock_logger,
            event_bus=self.mock_bus
        )

    def test_execute_success(self):
        # 🏁 Escenario: La base de datos devuelve un ID 42
        self.mock_db.execute.return_value = 42
        self.mock_identity.hash_password.return_value = "hashed_password" # Mock hash behavior
        
        test_data = {"name": "Test Real", "email": "real@test.com", "password": "secure123"}
        
        # 🚀 Ejecución
        result = self.plugin.execute(test_data)
        
        # ✅ Verificaciones de lógica de negocio
        self.assertTrue(result["success"])
        self.assertEqual(result["user"]["id"], 42)
        self.assertEqual(result["user"]["name"], "Test Real")
        
        # 🛡️ Verificación de efectos secundarios (INFRA-SWAPPING)
        # Comprobamos que el plugin llamó a la DB con el SQL correcto
        self.mock_identity.hash_password.assert_called_with("secure123")
        self.mock_db.execute.assert_called_once()
        query = self.mock_db.execute.call_args[0][0]
        self.assertIn("INSERT INTO users", query)
        
        # Comprobamos que avisó al EventBus
        self.mock_bus.publish.assert_called_with("users.created", result["user"])
        
        print("\n[OK] Test de plugin REAL finalizado con éxito y aislamiento total.")

if __name__ == "__main__":
    unittest.main()
