"""ROADMAP Issue 37, scope 2: request fields compared within a domain."""

import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.field_divergence_linter_plugin import FieldDivergenceLinterPlugin


def make_plugin():
    container = MagicMock()
    container.registry = MagicMock()
    return FieldDivergenceLinterPlugin(container=container, logger=MagicMock())


def _write_plugin(root, domain, filename, source):
    plugins_dir = root / "domains" / domain / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / filename).write_text(source)


CREATE_SRC = """
from pydantic import BaseModel, Field

class CreateUserRequest(BaseModel):
    password: str = Field(min_length=8)
"""


# Divergences in the real repo that are DELIBERATE, with the reason. Unlike
# domain isolation or table ownership — where clean is an invariant — this
# linter is advisory by design: divergence can be correct. So the gate is not
# "zero findings", it is "zero findings we have not already accepted", which
# still fails CI the moment a NEW one appears.
ACCEPTED_DIVERGENCES = {
    # login validates a password being VERIFIED, not one being set: rejecting
    # short input at login would only leak the policy and lock out legacy
    # accounts. The 8-char rule belongs on create/update, where it is enforced.
    "password.min_length",
}


@pytest.mark.anyio
async def test_real_repo_has_no_unaccepted_field_divergence():
    """CI gate: no divergence in the actual codebase beyond the accepted ones."""
    findings = make_plugin()._check_field_divergence()
    unexpected = [
        w for w in findings
        if not any(f"'{accepted}'" in w for accepted in ACCEPTED_DIVERGENCES)
    ]
    assert unexpected == []


@pytest.mark.anyio
async def test_detects_divergent_constraint_between_sibling_plugins(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "users", "create_user_plugin.py", CREATE_SRC)
    _write_plugin(tmp_path, "users", "update_user_plugin.py", """
from pydantic import BaseModel, Field

class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=6)
""")

    monkeypatch.chdir(tmp_path)
    warnings = make_plugin()._check_field_divergence()

    assert len(warnings) == 1
    assert "'password.min_length'" in warnings[0]
    assert "create_user_plugin.py:CreateUserRequest" in warnings[0]
    assert "update_user_plugin.py:UpdateUserRequest" in warnings[0]


@pytest.mark.anyio
async def test_agreeing_constraints_are_silent(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "users", "create_user_plugin.py", CREATE_SRC)
    _write_plugin(tmp_path, "users", "update_user_plugin.py", """
from pydantic import BaseModel, Field

class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8)
""")

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._check_field_divergence() == []


@pytest.mark.anyio
async def test_same_name_in_different_domains_is_not_compared(tmp_path, monkeypatch):
    """A shared NAME is not a shared CONCEPT: `name` in users and `name` in
    products legitimately differ (ROADMAP Issue 37, scoping rule 2)."""
    _write_plugin(tmp_path, "users", "create_user_plugin.py", """
from pydantic import BaseModel, Field

class CreateUserRequest(BaseModel):
    name: str = Field(max_length=100)
""")
    _write_plugin(tmp_path, "products", "create_product_plugin.py", """
from pydantic import BaseModel, Field

class CreateProductRequest(BaseModel):
    name: str = Field(max_length=300)
""")

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._check_field_divergence() == []


@pytest.mark.anyio
async def test_non_literal_constraints_are_never_guessed(tmp_path, monkeypatch):
    """A constraint built from a variable cannot be compared statically — the
    linter stays silent instead of reporting a false divergence."""
    _write_plugin(tmp_path, "users", "create_user_plugin.py", CREATE_SRC)
    _write_plugin(tmp_path, "users", "update_user_plugin.py", """
from pydantic import BaseModel, Field

MIN = 6

class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=MIN)
""")

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._check_field_divergence() == []


@pytest.mark.anyio
async def test_cosmetic_keywords_are_not_compared(tmp_path, monkeypatch):
    """description/examples differ per endpoint by design — comparing them
    would drown the real signal."""
    _write_plugin(tmp_path, "users", "create_user_plugin.py", """
from pydantic import BaseModel, Field

class CreateUserRequest(BaseModel):
    password: str = Field(min_length=8, description="New password")
""")
    _write_plugin(tmp_path, "users", "update_user_plugin.py", """
from pydantic import BaseModel, Field

class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, description="Replacement password")
""")

    monkeypatch.chdir(tmp_path)
    assert make_plugin()._check_field_divergence() == []


@pytest.mark.anyio
async def test_on_boot_publishes_warnings_to_registry(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "users", "create_user_plugin.py", CREATE_SRC)
    _write_plugin(tmp_path, "users", "update_user_plugin.py", """
from pydantic import BaseModel, Field

class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=6)
""")

    monkeypatch.chdir(tmp_path)
    container = MagicMock()
    registry = MagicMock()
    container.registry = registry
    plugin = FieldDivergenceLinterPlugin(container=container, logger=MagicMock())

    await plugin.on_boot()

    registry.register_domain_metadata.assert_called_once()
    domain, key, warnings = registry.register_domain_metadata.call_args[0]
    assert (domain, key) == ("devtools", "field_divergence_warnings")
    assert len(warnings) == 1
