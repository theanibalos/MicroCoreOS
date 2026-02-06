# infrastructure/repositories/sqlite_user_repository.py
# Clean Architecture: Repository Implementation (Adapter)

import sqlite3
from typing import Optional
from ..domain.repositories.user_repository import IUserRepository


class SqliteUserRepository(IUserRepository):
    """
    Concrete implementation of IUserRepository using SQLite.
    This is an ADAPTER in hexagonal architecture terminology.
    """

    def __init__(self, db):
        self._db = db

    def save(self, name: str, email: str) -> int:
        cursor = self._db.cursor()
        cursor.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (name, email)
        )
        return cursor.lastrowid
