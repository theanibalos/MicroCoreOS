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
        """Initializes the database and ensures migration history table exists"""
        print(f"[System] SqliteTool: Preparing database at '{self._db_path}'...")
        # Ensure the file exists
        if not os.path.exists(self._db_path):
            with open(self._db_path, "w") as f:
                pass
        
        # Create migrations history table
        self.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                filename TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domain, filename)
            )
        """)
        
    def on_boot_complete(self, container):
        """Executes pending .sql migrations found in domains/*/migrations/ directories"""
        print("[System] SqliteTool: Checking for pending migrations...")
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return

        for domain in os.listdir(domains_dir):
            migrations_dir = os.path.join(domains_dir, domain, "migrations")
            if not os.path.isdir(migrations_dir):
                continue
            
            # Find and sort .sql migration files
            migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])
            for filename in migration_files:
                # Check if already applied
                applied = self.query(
                    "SELECT 1 FROM _migrations_history WHERE domain = ? AND filename = ?", 
                    (domain, filename)
                )
                
                if not applied:
                    print(f"  [Migration] Applying {domain}/{filename}...")
                    filepath = os.path.join(migrations_dir, filename)
                    with open(filepath, "r", encoding="utf-8") as file:
                        sql_script = file.read()
                        
                    try:
                        # Execute SQL script (may contain multiple statements)
                        conn, cursor = self._get_conn()
                        cursor.executescript(sql_script)
                        # Record successful migration
                        cursor.execute(
                            "INSERT INTO _migrations_history (domain, filename) VALUES (?, ?)",
                            (domain, filename)
                        )
                        conn.commit()
                        print(f"  [Migration] Successfully applied {domain}/{filename}")
                    except Exception as e:
                        print(f"  [Migration/ERROR] Failed applying {domain}/{filename}: {e}")
                        # In a real scenario, you might want to halt the system here
                        raise e

    def get_interface_description(self) -> str:
        return """
        SQLite Persistence Tool (db):
        - PURPOSE: Persistent relational data storage using SQL.
        - IDEAL FOR: Domain entities (Users, Products), relational queries, and ACID transactions.
        - CAPABILITIES:
            - query(sql, params): Read data (SELECT). Returns list of tuples.
            - execute(sql, params): Write data (INSERT, UPDATE, DELETE). Returns last ID.
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