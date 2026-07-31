import ast
import shutil
from pathlib import Path

from tools.context import scanners


def test_extract_ast_models_simple_and_nested():
    code = """
from pydantic import BaseModel, EmailStr
from typing import Optional

class UserData(BaseModel):
    id: int
    name: str
    email: EmailStr

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class CreateUserResponse(BaseModel):
    success: bool
    data: Optional[UserData] = None
    error: Optional[str] = None
"""
    tree = ast.parse(code)
    models = scanners._extract_ast_models(tree)

    assert "CreateUserRequest" in models
    assert models["CreateUserRequest"] == "name: str, email: EmailStr, password: str"

    assert "CreateUserResponse" in models
    assert "data: Optional[UserData(id: int, name: str, email: EmailStr)]" in models["CreateUserResponse"]


def test_get_domain_endpoints_users(tmp_path, monkeypatch):
    """
    The scanner reads `domains/<name>/plugins` relative to the CWD, so the
    domain is staged here rather than borrowed from the repo. It is still the
    REAL plugin source being parsed — copied from the auth extra, which is
    where `microcoreos add auth` takes it from — so the assertions below keep
    describing what those plugins actually declare. Pointing at whichever
    domains happen to exist in this checkout is what broke this test when
    users moved out of `domains/`.
    """
    src = Path(__file__).resolve().parent.parent / "extras/available_domains/users/plugins"
    staged = tmp_path / "domains" / "users" / "plugins"
    staged.mkdir(parents=True)
    for name in ("create_user_plugin.py", "login_plugin.py"):
        shutil.copy2(src / name, staged / name)

    monkeypatch.chdir(tmp_path)
    endpoints = scanners._get_domain_endpoints("users")

    # Verify POST /users includes request and response schema fields
    post_users = [e for e in endpoints if e.startswith("POST /users")]
    assert len(post_users) == 1
    endpoint_str = post_users[0]
    assert "req: name: str, email: EmailStr, password: str" in endpoint_str
    assert "res: success: bool, data: Optional[CreatedUserData(id: int, name: str, email: EmailStr, roles: list[str])]" in endpoint_str

    # Verify POST /auth/login includes request schema fields
    login_users = [e for e in endpoints if e.startswith("POST /auth/login")]
    assert len(login_users) == 1
    assert "req: email: EmailStr, password: str" in login_users[0]


def test_phase_0_domain_appears_in_the_manifest(tmp_path, monkeypatch):
    """
    A domain that owns a table but has no plugin yet is exactly what phase 0
    produces. The manifest used to iterate registered PLUGINS only, so that
    domain was structurally invisible in the one document phase 0 is verified
    against: the migration applied, the manifest regenerated, and the new
    table appeared nowhere. Six turns of an observed session went into
    grepping for a section that could not exist.
    """
    from unittest.mock import MagicMock
    from tools.context.context_tool import ContextTool

    migrations = tmp_path / "domains" / "catalog" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_create_catalog.sql").write_text(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
    monkeypatch.chdir(tmp_path)

    container = MagicMock()
    container.list_tools.return_value = []
    container.registry.get_system_dump.return_value = {"plugins": {}}

    ContextTool()._generate_global_manifest(container, {
        "products": {"internal": False, "columns": [
            {"name": "id", "type": "int", "nullable": False,
             "default": None, "primary_key": True}], "unique": [],
            "foreign_keys": []},
    })

    manifest = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "### `catalog`" in manifest
    assert "**Table `products`**" in manifest
    # And it says which phase it is in, rather than only that a list is empty.
    assert "phase 0 only" in manifest


def test_a_domain_with_plugins_still_lists_them(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from tools.context.context_tool import ContextTool

    (tmp_path / "domains" / "shop" / "plugins").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    container = MagicMock()
    container.list_tools.return_value = []
    container.registry.get_system_dump.return_value = {
        "plugins": {"shop.ListPlugin": {"domain": "shop", "dependencies": ["db"]}}
    }
    container.get.return_value.get_subscribers.return_value = {}

    ContextTool()._generate_global_manifest(container, {})

    manifest = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "**Plugins**: shop.ListPlugin" in manifest
    assert "phase 0 only" not in manifest
