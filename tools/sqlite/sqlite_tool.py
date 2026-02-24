import os
import aiosqlite
import asyncio
from core.base_tool import BaseTool

class SqliteTool(BaseTool):
    def __init__(self):
        self._db_path = os.getenv("DB_PATH", "database.db")
        self._conn = None

    @property
    def name(self) -> str:
        return "db"

    async def _get_conn(self) -> aiosqlite.Connection:
        """Gets the shared connection or creates it"""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            # This allows accessing columns by name like row['id']
            self._conn.row_factory = aiosqlite.Row
        return self._conn

    async def setup(self):
        """Initializes the database and ensures migration history table exists"""
        print(f"[System] SqliteTool: Preparing database at '{self._db_path}'...")
        # Ensure the file exists
        if not os.path.exists(self._db_path):
            with open(self._db_path, "w") as f:
                pass
        
        # Create migrations history table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                filename TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domain, filename)
            )
        """)
        
    async def on_boot_complete(self, container):
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
                applied = await self.query(
                    "SELECT 1 FROM _migrations_history WHERE domain = ? AND filename = ?", 
                    (domain, filename)
                )
                
                if not applied:
                    print(f"  [Migration] Applying {domain}/{filename}...")
                    filepath = os.path.join(migrations_dir, filename)
                    with open(filepath, "r", encoding="utf-8") as file:
                        sql_script = file.read()
                        
                    conn = await self._get_conn()
                    try:
                        await conn.execute("BEGIN TRANSACTION")
                        
                        # Split by semicolon and execute one by one
                        statements = [s.strip() for s in sql_script.split(';') if s.strip()]
                        for statement in statements:
                            await conn.execute(statement)
                        
                        # Record successful migration
                        await conn.execute(
                            "INSERT INTO _migrations_history (domain, filename) VALUES (?, ?)",
                            (domain, filename)
                        )
                        await conn.commit()
                        print(f"  [Migration] Successfully applied {domain}/{filename}")
                    except Exception as e:
                        await conn.rollback()
                        print(f"  [Migration/ERROR] Failed applying {domain}/{filename}: {e}")
                        raise e

    def get_interface_description(self) -> str:
        return """
        Async SQLite Persistence Tool (db):
        - PURPOSE: Persistent relational data storage using SQL (Asynchronous).
        - CAPABILITIES:
            - await query(sql, params): Read data (SELECT). Returns list of rows.
            - await execute(sql, params): Write data (INSERT, UPDATE, DELETE). Returns last ID.
        """

    async def query(self, sql, params=()):
        conn = await self._get_conn()
        async with conn.execute(sql, params) as cursor:
            # We convert it back to a list of tuples for compatibility with basic plugins
            # but using Row would be better. For now, let's keep it simple.
            rows = await cursor.fetchall()
            return [tuple(row) for row in rows]

    async def execute(self, sql, params=()):
        conn = await self._get_conn()
        async with conn.execute(sql, params) as cursor:
            row_id = cursor.lastrowid
            await conn.commit()
            return row_id

    async def shutdown(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            print("[SqliteTool] Database connection closed.")