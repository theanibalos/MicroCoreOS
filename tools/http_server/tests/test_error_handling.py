import unittest
import sys
import os
from fastapi.testclient import TestClient

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from tools.http_server.http_server_tool import HttpServerTool

class TestHttpServerTool(unittest.TestCase):
    def test_exception_handling(self):
        tool = HttpServerTool()

        # Define a handler that raises an exception with sensitive info
        def buggy_handler(data):
            raise ValueError("SENSITIVE_DATA_LEAK")

        tool.add_endpoint("/buggy", "GET", buggy_handler)

        # TestClient to simulate requests
        client = TestClient(tool.app)

        response = client.get("/buggy")

        self.assertEqual(response.status_code, 500)

        # Verify that the response contains generic error message, not the sensitive one
        self.assertEqual(response.json(), {"success": False, "error": "Internal Server Error"})

if __name__ == "__main__":
    unittest.main()
