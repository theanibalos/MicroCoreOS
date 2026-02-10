import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from domains.users.plugins.create_user_plugin import CreateUserPlugin
from domains.users.plugins.update_user_plugin import UpdateUserPlugin
from domains.users.plugins.delete_user_plugin import DeleteUserPlugin

class TestSecurityErrorHandling(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock()
        self.mock_db = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_bus = MagicMock()

    def test_create_user_no_leak(self):
        # Setup: DB raises a generic exception with internal details
        internal_error = "Syntax error near 'FOO'"
        self.mock_db.execute.side_effect = Exception(internal_error)

        plugin = CreateUserPlugin(self.mock_http, self.mock_db, self.mock_logger, self.mock_bus)
        result = plugin.execute({"name": "Test", "email": "test@example.com"})

        # Expectation: The error message should NOT contain the internal error
        self.assertFalse(result["success"], "Should fail gracefully")
        self.assertNotIn(internal_error, result.get("error", ""), "Should not leak internal error details")
        self.assertIn("internal error", result.get("error", "").lower(), "Should return a generic error message")

    def test_update_user_no_leak(self):
        # Setup: DB raises a generic exception with internal details
        internal_error = "Table 'users' has no column named 'foo'"
        self.mock_db.query.side_effect = Exception(internal_error)

        plugin = UpdateUserPlugin(self.mock_http, self.mock_db, self.mock_logger, self.mock_bus)
        result = plugin.execute({"id": 1, "name": "Updated"})

        # Expectation: The error message should NOT contain the internal error
        self.assertFalse(result["success"], "Should fail gracefully")
        self.assertNotIn(internal_error, result.get("error", ""), "Should not leak internal error details")
        self.assertIn("internal error", result.get("error", "").lower(), "Should return a generic error message")

    def test_delete_user_no_leak(self):
        # Setup: DB raises a generic exception with internal details
        internal_error = "Foreign key constraint failed: 'orders.user_id'"
        self.mock_db.query.return_value = [{"id": 1}] # User exists
        self.mock_db.execute.side_effect = Exception(internal_error)

        plugin = DeleteUserPlugin(self.mock_http, self.mock_db, self.mock_logger, self.mock_bus)
        result = plugin.execute({"id": 1})

        # Expectation: The error message should NOT contain the internal error
        self.assertFalse(result["success"], "Should fail gracefully")
        self.assertNotIn(internal_error, result.get("error", ""), "Should not leak internal error details")
        self.assertIn("internal error", result.get("error", "").lower(), "Should return a generic error message")

if __name__ == "__main__":
    unittest.main()
