import sys
import os
import unittest
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from tools.http_server.http_server_tool import HttpServerTool

class TestSecurityVulnerability(unittest.TestCase):
    def setUp(self):
        self.http_tool = HttpServerTool()
        self.client = TestClient(self.http_tool.app)

    def test_auth_bypass_via_body_injection(self):
        # 1. Setup a protected endpoint that returns the user ID from _auth
        def mock_decoder(token):
            if token == "valid-token":
                return {"user_id": 1, "role": "user"}
            raise Exception("Invalid token")

        guard = self.http_tool.get_bearer_guard(mock_decoder)

        def protected_handler(data):
            auth = data.get("_auth", {})
            return {"user_id": auth.get("user_id"), "role": auth.get("role")}

        self.http_tool.add_endpoint(
            path="/protected",
            method="POST",
            handler=protected_handler,
            security_guard=guard
        )

        # 2. Attack: Send request with valid token but inject malicious _auth in body
        headers = {"Authorization": "Bearer valid-token"}
        malicious_body = {
            "some_data": "value",
            "_auth": {"user_id": 999, "role": "admin"}  # Attempt to escalate privilege
        }

        response = self.client.post("/protected", json=malicious_body, headers=headers)

        # 3. Assert: If vulnerability exists, the returned user_id will be 999
        data = response.json()
        print(f"Auth Bypass Response: {data}")

        # We expect the legitimate user_id (1). If 999 is returned, it means body injection worked.
        self.assertEqual(data.get("user_id"), 1, "CRITICAL: Auth bypass successful! _auth was overwritten by body data.")

    def test_leaky_error_handling(self):
        # 1. Setup an endpoint that raises an exception with sensitive info
        sensitive_info = "Database connection failed at 192.168.1.5:5432"
        def failing_handler(data):
            raise ValueError(sensitive_info)

        self.http_tool.add_endpoint(
            path="/error",
            method="GET",
            handler=failing_handler
        )

        # 2. Trigger error
        response = self.client.get("/error")

        # 3. Assert: We should NOT see the internal error details
        data = response.json()
        print(f"Error Leak Response: {data}")

        self.assertIn("error", data)
        # Check if sensitive info is NOT leaked
        self.assertNotIn(sensitive_info, data["error"], "CRITICAL: Leaky error message! Exposed internal details.")
        self.assertEqual(data["error"], "Internal Server Error", "Should return generic error message")

if __name__ == "__main__":
    unittest.main()
