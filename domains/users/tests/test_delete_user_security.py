import unittest
import sys
import os
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from domains.users.plugins.delete_user_plugin import DeleteUserPlugin

class TestDeleteUserSecurity(unittest.TestCase):

    def setUp(self):
        self.mock_http = MagicMock()
        self.mock_db = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_bus = MagicMock()
        self.mock_identity = MagicMock()

        # Instantiate WITH identity (fixed state)
        self.plugin = DeleteUserPlugin(
            http=self.mock_http,
            db=self.mock_db,
            logger=self.mock_logger,
            event_bus=self.mock_bus,
            identity=self.mock_identity
        )

    def test_delete_user_without_auth_fails(self):
        """
        Verify that deletion without auth fails.
        """
        result = self.plugin.execute({"id": 1})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Unauthorized")
        self.mock_db.execute.assert_not_called()

    def test_delete_other_user_fails(self):
        """
        Verify that deleting another user fails (Authorization).
        """
        # User 1 tries to delete User 2
        result = self.plugin.execute({"id": 2, "_auth": {"user_id": 1}})
        self.assertFalse(result["success"])
        self.assertIn("Forbidden", result["error"])
        self.mock_db.execute.assert_not_called()

    def test_delete_own_user_succeeds(self):
        """
        Verify that deleting own user succeeds.
        """
        # User 1 tries to delete User 1
        self.mock_db.query.return_value = [(1,)] # User exists

        result = self.plugin.execute({"id": 1, "_auth": {"user_id": 1}})
        self.assertTrue(result["success"])
        self.mock_db.execute.assert_called_with("DELETE FROM users WHERE id = ?", (1,))

if __name__ == "__main__":
    unittest.main()
