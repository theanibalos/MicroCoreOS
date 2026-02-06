import os
import sqlite3
import threading
from core.base_tool import BaseTool

class SqliteTool(BaseTool):
    def __init__(self):
        self._local = threading.local()
        # Read directly from global environment (main.py already loaded it)
        self._db_path = os.getenv("DB_PATH", "database.db")

    @property
    def name(self) -> str:
        return "db"

    def _get_conn(self):
        """Gets the unique connection for the current thread"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = self._local.conn.cursor()
        return self._local.conn, self._local.cursor

    def setup(self):
        """Initializes the migrations folder and database"""
        print(f"[System] SqliteTool: Preparing database at '{self._db_path}'...")
        # Ensure the file exists
        if not os.path.exists(self._db_path):
            with open(self._db_path, "w") as f:
                pass
        
    def on_boot_complete(self, container):
        """In the future, this will handle migrations"""

    def get_interface_description(self) -> str:
        return """
        SQLite Tool (db):
        - query(sql, params): Read query (SELECT).
        - execute(sql, params): Write operations (INSERT, UPDATE, DELETE).
        """

    def query(self, sql, params=()):
        _, cursor = self._get_conn()
        cursor.execute(sql, params)
        return cursor.fetchall()

    def execute(self, sql, params=()):
        conn, cursor = self._get_conn()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.lastrowid

    def shutdown(self):
        # Being daemon threads, the OS will clean up.
        pass