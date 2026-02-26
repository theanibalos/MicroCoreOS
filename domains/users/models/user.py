"""
UserEntity — Mirror of the `users` table in the database.

RULE: This file contains ONE thing: the DB entity.
      HTTP request/response schemas belong inside each plugin.
      Do NOT add request models here.
"""

from pydantic import BaseModel, EmailStr


class UserEntity(BaseModel):
    id: int | None = None
    name: str
    email: EmailStr
    password_hash: str | None = None
