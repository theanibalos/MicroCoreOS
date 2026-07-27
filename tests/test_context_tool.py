import ast
import pytest
from tools.context.context_tool import ContextTool


def test_extract_ast_models_simple_and_nested():
    tool = ContextTool()
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
    models = tool._extract_ast_models(tree)

    assert "CreateUserRequest" in models
    assert models["CreateUserRequest"] == "name: str, email: EmailStr, password: str"

    assert "CreateUserResponse" in models
    assert "data: Optional[UserData(id: int, name: str, email: EmailStr)]" in models["CreateUserResponse"]


def test_get_domain_endpoints_users():
    tool = ContextTool()
    endpoints = tool._get_domain_endpoints("users")

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
