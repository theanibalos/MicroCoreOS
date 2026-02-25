"""
Configuration Tool — MicroCoreOS
==================================

Provides type-safe, validated access to environment variables for plugins.

NOTE: Tools read their own env vars directly with os.getenv() in __init__() —
this tool is intended for PLUGINS that need dynamic config access or fail-fast
validation of required variables at boot time.

PUBLIC CONTRACT (what plugins use):
────────────────────────────────────────────────────────────────────────────────

    # Declare required variables in on_boot() — fails early if any are missing
    def on_boot(self):
        self.config.require("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")
        ...

    # Access a value (returns None if missing)
    api_key = self.config.get("STRIPE_SECRET_KEY")

    # Access with a default
    timeout = self.config.get("REQUEST_TIMEOUT", default="30")

    # Access as a required value (raises EnvironmentError if missing)
    db_url = self.config.get("DATABASE_URL", required=True)
"""

import os
from typing import Optional
from core.base_tool import BaseTool


class ConfigTool(BaseTool):

    @property
    def name(self) -> str:
        return "config"

    async def setup(self) -> None:
        pass

    def get_interface_description(self) -> str:
        return """
        Configuration Tool (config):
        - PURPOSE: Validated access to environment variables for plugins.
          Tools read their own env vars with os.getenv() — this tool is for plugins.
        - CAPABILITIES:
            - get(key, default=None, required=False) -> str | None:
                Returns the value of the environment variable.
                If required=True and the variable is not set, raises EnvironmentError.
            - require(*keys) -> None:
                Validates that all specified variables are set.
                Call in on_boot() to fail early with a clear error message.
                Example: self.config.require("STRIPE_KEY", "SENDGRID_KEY")
        """

    def get(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """
        Returns the value of an environment variable.

        Args:
            key:      The environment variable name.
            default:  Value to return if the variable is not set (default: None).
            required: If True and the variable is not set, raises EnvironmentError.

        Raises:
            EnvironmentError: If required=True and the variable is missing.
        """
        value = os.environ.get(key, default)
        if required and value is None:
            raise EnvironmentError(
                f"[Config] Required environment variable '{key}' is not set. "
                f"Check your .env file or environment configuration."
            )
        return value

    def require(self, *keys: str) -> None:
        """
        Fail-fast validation. Raises EnvironmentError if any of the specified
        variables are missing or empty.

        Call in on_boot() to surface configuration errors at startup,
        not during a live request.

        Example:
            async def on_boot(self):
                self.config.require("STRIPE_SECRET_KEY", "SENDGRID_API_KEY")
                ...

        Raises:
            EnvironmentError: Lists all missing variables in a single error.
        """
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            raise EnvironmentError(
                f"[Config] Missing required environment variables: {', '.join(missing)}. "
                f"Check your .env file or environment configuration."
            )
