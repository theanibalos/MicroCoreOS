import unittest
import sys
import os
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from domains.users.plugins.update_user_plugin import UpdateUserPlugin
from domains.users.models.user_model import UserModel

class TestUpdateUserSecurity(unittest.TestCase):
    """
    Security tests for UpdateUserPlugin.
    Verifies authentication and authorization enforcement.
    """

    def setUp(self):
        # Mocks
        self.mock_http = MagicMock()
        self.mock_db = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_bus = MagicMock()
        self.mock_identity = MagicMock()

        # Instantiate plugin with mocks (including identity)
        self.plugin = UpdateUserPlugin(
            http=self.mock_http,
            db=self.mock_db,
            logger=self.mock_logger,
            event_bus=self.mock_bus,
            identity=self.mock_identity
        )

    def test_update_without_auth_fails(self):
        """
        Verify that updating without _auth data fails.
        """
        # Scenario: User exists in DB
        user_id = 42

        # Execution: Update WITHOUT _auth
        data = {
            "id": user_id,
            "name": "Hacked Name"
        }

        result = self.plugin.execute(data)

        # Assertion
        self.assertFalse(result["success"])
        self.assertIn("Unauthorized", result["error"])
        self.mock_db.execute.assert_not_called()

    def test_update_wrong_user_fails(self):
        """
        Verify that updating a DIFFERENT user's profile fails (IDOR protection).
        """
        user_id = 42
        attacker_id = 666

        # Data has _auth for Attacker, but tries to update User 42
        data = {
            "_auth": {"user_id": attacker_id},
            "id": user_id,
            "name": "Hacked Name"
        }

        result = self.plugin.execute(data)

        # Assertion
        self.assertFalse(result["success"])
        self.assertIn("Forbidden", result["error"])
        self.mock_db.execute.assert_not_called()

    def test_update_correct_user_succeeds(self):
        """
        Verify that updating OWN profile succeeds.
        """
        user_id = 42

        # Mock DB finding the user
        self.mock_db.query.side_effect = [
            [(user_id, "Old Name", "old@test.com", "hash")], # First query: check exists
            [(user_id, "New Name", "old@test.com", "hash")]  # Second query: get updated
        ]

        # Data has _auth for User 42, and tries to update User 42
        data = {
            "_auth": {"user_id": user_id},
            "id": user_id,
            "name": "New Name"
        }

        result = self.plugin.execute(data)

        # Assertion
        self.assertTrue(result["success"])
        self.assertEqual(result["user"]["name"], "New Name")
        self.mock_db.execute.assert_called_once()

if __name__ == "__main__":
    unittest.main()
