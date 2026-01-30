import sqlite3
from core.base_tool import BaseTool

class SqliteTool(BaseTool):
    @property
    def name(self) -> str:
        return "db"

    def setup(self):
        """Inicializa la conexión y crea una tabla de prueba"""
        self.conn = sqlite3.connect("database.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        # Creamos una tabla inicial para que la IA tenga donde trabajar
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL
            )
        """)
        self.conn.commit()
        print("[System] SqliteTool: Base de datos lista y conectada.")

    def get_interface_description(self) -> str:
        return """
        Herramienta SQLite (db):
        - query(sql, params): Ejecuta una consulta de lectura (SELECT).
        - execute(sql, params): Ejecuta una escritura (INSERT, UPDATE, DELETE).
        - commit(): Guarda los cambios en disco.
        """

    def query(self, sql, params=()):
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def execute(self, sql, params=()):
        self.cursor.execute(sql, params)
        self.conn.commit()
        return self.cursor.lastrowid

    def shutdown(self):
        self.conn.close()