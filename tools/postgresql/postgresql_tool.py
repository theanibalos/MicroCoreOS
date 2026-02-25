"""
PostgreSQL Tool — Gold-Standard Database Contract for MicroCoreOS
=================================================================

This is the REFERENCE IMPLEMENTATION for database tools in MicroCoreOS.
Any new database tool (MySQL, MariaDB, etc.) MUST follow this contract.

CONTRATO PÚBLICO (lo que los plugins usan):
─────────────────────────────────────────────
    rows  = await db.query("SELECT * FROM users WHERE age > $1", [18])
    row   = await db.query_one("SELECT * FROM users WHERE id = $1", [5])
    newid = await db.execute("INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"])
    count = await db.execute("UPDATE users SET active = $1", [True])
    await db.execute_many("INSERT INTO logs (msg) VALUES ($1)", [["a"], ["b"]])

    async with db.transaction() as tx:
        uid = await tx.execute("INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"])
        await tx.execute("INSERT INTO profiles (user_id) VALUES ($1)", [uid])
        # COMMIT automático al salir. ROLLBACK automático si hay excepción.

    ok = await db.health_check()

PLACEHOLDERS: PostgreSQL usa $1, $2, $3... (NO '?' como SQLite).
"""

import os
import asyncpg
from core.base_tool import BaseTool


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXCEPCIONES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DatabaseError(Exception):
    """Error genérico de base de datos. Envuelve excepciones de asyncpg."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Error de conexión al servidor PostgreSQL."""
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRANSACTION CONTEXT MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Transaction:
    """
    Transacción explícita sobre una conexión adquirida del pool.

    Uso:
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO ...", [...])
            await tx.execute("UPDATE ...", [...])
            rows = await tx.query("SELECT ...", [...])
        # COMMIT automático al salir del bloque.
        # ROLLBACK automático si ocurre cualquier excepción.

    El context manager gestiona:
    1. Adquirir una conexión del pool.
    2. Abrir una transacción PostgreSQL real (BEGIN).
    3. Hacer COMMIT si todo sale bien.
    4. Hacer ROLLBACK si ocurre una excepción.
    5. Devolver la conexión al pool SIEMPRE.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool: asyncpg.Pool = pool
        self._conn: asyncpg.Connection | None = None
        self._tx: asyncpg.connection.transaction.Transaction | None = None

    async def __aenter__(self) -> "Transaction":
        try:
            self._conn = await self._pool.acquire()
            self._tx = self._conn.transaction()
            await self._tx.start()
        except asyncpg.PostgresError as e:
            # Si falla la adquisición o el BEGIN, limpiamos y propagamos
            if self._conn is not None:
                await self._pool.release(self._conn)
                self._conn = None
            raise DatabaseConnectionError(f"Failed to start transaction: {e}") from e
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            if exc_type is None:
                # Sin errores → COMMIT
                await self._tx.commit()
            else:
                # Con errores → ROLLBACK
                await self._tx.rollback()
        finally:
            # SIEMPRE devolver la conexión al pool
            if self._conn is not None:
                await self._pool.release(self._conn)
                self._conn = None
        # No suprimimos la excepción (return False)
        return False

    # ─── API dentro de la transacción ─────────────────────

    async def query(self, sql: str, params: list | None = None) -> list[dict]:
        """SELECT dentro de la transacción. Retorna list[dict]."""
        params = params or []
        try:
            rows = await self._conn.fetch(sql, *params)
            return [dict(row) for row in rows]
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction query failed: {e}") from e

    async def query_one(self, sql: str, params: list | None = None) -> dict | None:
        """SELECT de un solo registro dentro de la transacción. Retorna dict o None."""
        params = params or []
        try:
            row = await self._conn.fetchrow(sql, *params)
            return dict(row) if row is not None else None
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction query_one failed: {e}") from e

    async def execute(self, sql: str, params: list | None = None) -> int | None:
        """
        INSERT/UPDATE/DELETE dentro de la transacción.

        - Si el SQL tiene RETURNING, retorna el valor de la primera columna
          del primer registro (típicamente el ID generado).
        - Si no tiene RETURNING, retorna el número de filas afectadas.
        """
        params = params or []
        try:
            # Intentar fetchrow primero (para RETURNING)
            if "RETURNING" in sql.upper():
                row = await self._conn.fetchrow(sql, *params)
                if row is not None:
                    return row[0]
                return None
            else:
                result = await self._conn.execute(sql, *params)
                return _parse_affected_rows(result)
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction execute failed: {e}") from e


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILIDADES INTERNAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_affected_rows(status: str) -> int:
    """
    Parsea el string de status de asyncpg (ej: 'UPDATE 3', 'DELETE 1', 'INSERT 0 1')
    y extrae el número de filas afectadas.
    """
    try:
        parts = status.split()
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POSTGRESQL TOOL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PostgresqlTool(BaseTool):
    """
    PostgreSQL persistence tool for MicroCoreOS.

    Uses asyncpg with a connection pool for high-performance,
    non-blocking database access. This is the gold-standard
    implementation that all database tools should follow.
    """

    # ─── IDENTITY ─────────────────────────────────────────

    @property
    def name(self) -> str:
        return "db"

    # ─── CONSTRUCTOR ──────────────────────────────────────
    #
    # Solo lectura de configuración. Cero lógica, cero I/O.
    # El pool se crea en setup(), NO aquí.
    #

    def __init__(self) -> None:
        self._host: str = os.getenv("PG_HOST", "localhost")
        self._port: int = int(os.getenv("PG_PORT", "5432"))
        self._user: str = os.getenv("PG_USER", "postgres")
        self._password: str = os.getenv("PG_PASSWORD", "")
        self._database: str = os.getenv("PG_DATABASE", "postgres")
        self._min_pool: int = int(os.getenv("PG_MIN_POOL", "1"))
        self._max_pool: int = int(os.getenv("PG_MAX_POOL", "10"))
        self._pool: asyncpg.Pool | None = None

    # ─── LIFECYCLE: setup() ───────────────────────────────
    #
    # Fase de infraestructura. Se ejecuta ANTES de los plugins.
    # Responsabilidades:
    #   1. Crear el pool de conexiones.
    #   2. Crear la tabla interna de historial de migraciones.
    #

    async def setup(self) -> None:
        print(f"[System] PostgresqlTool: Connecting to {self._host}:{self._port}/{self._database}...")

        try:
            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                min_size=self._min_pool,
                max_size=self._max_pool,
            )
        except (asyncpg.PostgresError, OSError, ConnectionRefusedError) as e:
            raise DatabaseConnectionError(
                f"Cannot connect to PostgreSQL at {self._host}:{self._port}/{self._database}: {e}"
            ) from e

        # Crear tabla interna de migraciones
        await self.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_history (
                id          SERIAL PRIMARY KEY,
                domain      TEXT NOT NULL,
                filename    TEXT NOT NULL,
                applied_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(domain, filename)
            )
        """)

        print(f"[System] PostgresqlTool: Pool ready (min={self._min_pool}, max={self._max_pool}).")

    # ─── LIFECYCLE: on_boot_complete() ────────────────────
    #
    # Se ejecuta DESPUÉS de que todos los tools y plugins están cargados.
    # Responsabilidad: ejecutar migraciones SQL pendientes.
    #
    # Las migraciones se buscan en: domains/*/migrations/*.sql
    # Se aplican en orden alfabético, dentro de una transacción por archivo.
    # Si una migración falla, se hace ROLLBACK de esa migración
    # y se detiene la ejecución (raise) para no dejar el sistema inconsistente.
    #

    async def on_boot_complete(self, container) -> None:
        print("[System] PostgresqlTool: Checking for pending migrations...")
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return

        for domain in sorted(os.listdir(domains_dir)):
            migrations_dir = os.path.join(domains_dir, domain, "migrations")
            if not os.path.isdir(migrations_dir):
                continue

            migration_files = sorted(
                f for f in os.listdir(migrations_dir) if f.endswith(".sql")
            )

            for filename in migration_files:
                # Verificar si ya fue aplicada
                already_applied = await self.query_one(
                    "SELECT 1 FROM _migrations_history WHERE domain = $1 AND filename = $2",
                    [domain, filename],
                )
                if already_applied:
                    continue

                print(f"  [Migration] Applying {domain}/{filename}...")
                filepath = os.path.join(migrations_dir, filename)

                with open(filepath, "r", encoding="utf-8") as f:
                    sql_script = f.read()

                # Cada migración en su propia transacción
                async with self.transaction() as tx:
                    # Ejecutar cada statement del archivo
                    statements = [s.strip() for s in sql_script.split(";") if s.strip()]
                    for statement in statements:
                        await tx.execute(statement)

                    # Registrar migración exitosa
                    await tx.execute(
                        "INSERT INTO _migrations_history (domain, filename) VALUES ($1, $2)",
                        [domain, filename],
                    )

                print(f"  [Migration] ✅ Applied {domain}/{filename}")

    # ─── LIFECYCLE: shutdown() ────────────────────────────
    #
    # Cierra el pool de conexiones de forma ordenada.
    # Espera a que las conexiones activas terminen.
    #

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            print("[PostgresqlTool] Connection pool closed.")

    # ─── PUBLIC API: query() ──────────────────────────────
    #
    # Ejecuta un SELECT y retorna TODOS los registros.
    #
    # Parámetros:
    #   sql:    str           — Query SQL con placeholders $1, $2...
    #   params: list | None   — Valores para los placeholders
    #
    # Retorna: list[dict]
    #   - Lista vacía si no hay resultados.
    #   - Cada dict tiene como keys los nombres de las columnas.
    #
    # Ejemplo:
    #   rows = await db.query("SELECT id, name FROM users WHERE age > $1", [18])
    #   # [{"id": 1, "name": "Ana"}, {"id": 2, "name": "Luis"}]
    #

    async def query(self, sql: str, params: list | None = None) -> list[dict]:
        params = params or []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(row) for row in rows]
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Query failed: {e}") from e

    # ─── PUBLIC API: query_one() ──────────────────────────
    #
    # Ejecuta un SELECT y retorna el PRIMER registro o None.
    #
    # Parámetros:
    #   sql:    str           — Query SQL con placeholders $1, $2...
    #   params: list | None   — Valores para los placeholders
    #
    # Retorna: dict | None
    #   - None si no hay resultados.
    #   - dict con keys = nombres de columnas.
    #
    # Ejemplo:
    #   user = await db.query_one("SELECT * FROM users WHERE id = $1", [5])
    #   # {"id": 5, "name": "Ana", "email": "ana@mail.com"} or None
    #

    async def query_one(self, sql: str, params: list | None = None) -> dict | None:
        params = params or []
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                return dict(row) if row is not None else None
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Query failed: {e}") from e

    # ─── PUBLIC API: execute() ────────────────────────────
    #
    # Ejecuta INSERT, UPDATE o DELETE.
    #
    # Parámetros:
    #   sql:    str           — SQL con placeholders $1, $2...
    #   params: list | None   — Valores para los placeholders
    #
    # Retorna: int | None
    #   - Con RETURNING: el valor de la primera columna del primer registro
    #     (típicamente el ID generado).
    #   - Sin RETURNING: el número de filas afectadas (int).
    #
    # Ejemplo con RETURNING:
    #   new_id = await db.execute(
    #       "INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"]
    #   )
    #   # 42
    #
    # Ejemplo sin RETURNING:
    #   affected = await db.execute(
    #       "UPDATE users SET active = $1 WHERE age < $2", [False, 18]
    #   )
    #   # 3
    #

    async def execute(self, sql: str, params: list | None = None) -> int | None:
        params = params or []
        try:
            async with self._pool.acquire() as conn:
                if "RETURNING" in sql.upper():
                    row = await conn.fetchrow(sql, *params)
                    if row is not None:
                        return row[0]
                    return None
                else:
                    result = await conn.execute(sql, *params)
                    return _parse_affected_rows(result)
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Execute failed: {e}") from e

    # ─── PUBLIC API: execute_many() ───────────────────────
    #
    # Ejecuta la misma sentencia SQL con múltiples sets de parámetros.
    # Optimizado internamente por asyncpg (pipeline).
    #
    # Parámetros:
    #   sql:         str         — SQL con placeholders $1, $2...
    #   params_list: list[list]  — Lista de listas de parámetros.
    #
    # Retorna: None
    #
    # Ejemplo:
    #   await db.execute_many(
    #       "INSERT INTO logs (level, msg) VALUES ($1, $2)",
    #       [["INFO", "Started"], ["ERROR", "Crashed"], ["INFO", "Recovered"]]
    #   )
    #

    async def execute_many(self, sql: str, params_list: list[list]) -> None:
        try:
            async with self._pool.acquire() as conn:
                # asyncpg.executemany espera una lista de tuples
                await conn.executemany(sql, [tuple(p) for p in params_list])
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Execute many failed: {e}") from e

    # ─── PUBLIC API: transaction() ────────────────────────
    #
    # Abre una transacción explícita usando un context manager async.
    # Dentro del bloque, todas las operaciones comparten la misma
    # conexión y transacción PostgreSQL.
    #
    # - COMMIT automático al salir del bloque sin errores.
    # - ROLLBACK automático si ocurre cualquier excepción.
    # - La conexión se devuelve al pool SIEMPRE.
    #
    # Ejemplo:
    #   async with db.transaction() as tx:
    #       user_id = await tx.execute(
    #           "INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"]
    #       )
    #       await tx.execute(
    #           "INSERT INTO profiles (user_id, bio) VALUES ($1, $2)",
    #           [user_id, "Hello!"]
    #       )
    #   # Si cualquier execute falla, todo se revierte.
    #

    def transaction(self) -> Transaction:
        if self._pool is None:
            raise DatabaseConnectionError("Cannot start transaction: pool is not initialized.")
        return Transaction(self._pool)

    # ─── PUBLIC API: health_check() ───────────────────────
    #
    # Verifica que el pool está activo y la BD responde.
    # Útil para el Registry y monitoring.
    #
    # Retorna: bool
    #   - True si la conexión funciona.
    #   - False si hay algún error.
    #

    async def health_check(self) -> bool:
        try:
            if self._pool is None:
                return False
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # ─── INTERFACE DESCRIPTION ────────────────────────────

    def get_interface_description(self) -> str:
        return """
        Async PostgreSQL Persistence Tool (db):
        - PURPOSE: Production-grade relational data storage using PostgreSQL with connection pooling.
        - PLACEHOLDERS: Use $1, $2, $3... (NOT '?' like SQLite).
        - CAPABILITIES:
            - await query(sql, params?) → list[dict]: Read multiple rows (SELECT).
            - await query_one(sql, params?) → dict | None: Read a single row (SELECT).
            - await execute(sql, params?) → int | None: Write data (INSERT/UPDATE/DELETE).
              With RETURNING: returns the first column value. Without: returns affected row count.
            - await execute_many(sql, params_list) → None: Batch writes with optimized pipeline.
            - async with transaction() as tx: Explicit transaction block with auto-commit/rollback.
              Inside tx: tx.query(), tx.query_one(), tx.execute() — same signatures.
            - await health_check() → bool: Verify database connectivity.
        - EXCEPTIONS: Raises DatabaseError or DatabaseConnectionError on failure.
        """
