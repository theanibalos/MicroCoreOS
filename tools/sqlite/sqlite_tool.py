import os
import sqlite3
import threading
from core.base_tool import BaseTool

class SqliteTool(BaseTool):
    def __init__(self):
        self._local = threading.local()
        # Leemos directamente del entorno global (main.py ya lo cargó)
        self._db_path = os.getenv("DB_PATH", "database.db")

    @property
    def name(self) -> str:
        return "db"

    def _get_conn(self):
        """Obtiene la conexión única para el hilo actual"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = self._local.conn.cursor()
        return self._local.conn, self._local.cursor

    def setup(self):
        """Inicializa la carpeta de migraciones y la base de datos"""
        print(f"[System] SqliteTool: Preparando base de datos en '{self._db_path}'...")
        # Aseguramos que el archivo existe
        if not os.path.exists(self._db_path):
            with open(self._db_path, "w") as f:
                pass
        
    def on_boot_complete(self, container):
        """En un futuro, se encargará de las migraciones"""

    def get_interface_description(self) -> str:
        return """
        Herramienta SQLite (db):
        - query(sql, params): Consulta de lectura (SELECT).
        - execute(sql, params): Escritura (INSERT, UPDATE, DELETE).
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
        # Al ser hilos daemon, el SO limpiará. 
        pass