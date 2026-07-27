"""
PostgreSQL Tool — Gold-Standard Database Contract for MicroCoreOS
=================================================================

This is the REFERENCE IMPLEMENTATION for database tools in MicroCoreOS.
Any new database tool (MySQL, MariaDB, etc.) MUST follow this contract.

PUBLIC CONTRACT (what plugins use):
─────────────────────────────────────────────
    rows  = await db.query("SELECT * FROM users WHERE age > $1", [18])
    row   = await db.query_one("SELECT * FROM users WHERE id = $1", [5])
    newid = await db.execute("INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"])
    count = await db.execute("UPDATE users SET active = $1", [True])
    await db.execute_many("INSERT INTO logs (msg) VALUES ($1)", [["a"], ["b"]])

    async with db.transaction() as tx:
        uid = await tx.execute("INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"])
        await tx.execute("INSERT INTO profiles (user_id) VALUES ($1)", [uid])
        # Auto-COMMIT on exit. Auto-ROLLBACK on exception.

    ok = await db.health_check()

ERROR CONTRACT (part of the gold standard — any db tool MUST match it):
─────────────────────────────────────────────
    Every failure raises DatabaseError carrying `kind` from a CLOSED
    vocabulary (see ERROR_KINDS), plus best-effort `table` / `columns`:

        try:
            await db.execute("INSERT INTO users (email) VALUES ($1)", [email])
        except Exception as e:
            if getattr(e, "kind", None) == "unique_violation":
                ...

    Plugins branch on `kind`, NEVER on str(e): the message text is
    engine-specific ('duplicate key value violates unique constraint
    "users_email_key"' here, "UNIQUE constraint failed: users.email" on
    SQLite), so text matching breaks silently on the swap.

PLACEHOLDERS: PostgreSQL uses $1, $2, $3... (NOT '?' like SQLite).
"""

import os
import re
import asyncio
import asyncpg
from microcoreos import BaseTool, ToolUnavailableError


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXCEPTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Error-kind vocabulary — CLOSED, shared VERBATIM with the SQLite tool.
# Same idea as the describe_schema type vocabulary, applied to failures: each
# engine reports constraint violations its own way (PostgreSQL: SQLSTATE,
# SQLite: message text), so the tool classifies and every db tool exposes the
# SAME set of values. Adding a value here means adding it to EVERY db tool.
ERROR_KINDS = (
    "unique_violation",
    "foreign_key_violation",
    "not_null_violation",
    "check_violation",
    "unknown",
)


class DatabaseError(Exception):
    """Generic database error. Wraps asyncpg exceptions.

    Carries the engine-independent classification of the failure:

        kind:    one of ERROR_KINDS — ALWAYS present.
        table:   table the violation happened on, or None.
        columns: tuple of column names involved, possibly empty.

    Plugins branch on `kind`, NEVER on str(e) — the message text is
    engine-specific and changes under your feet on an engine swap:

        except Exception as e:
            if getattr(e, "kind", None) == "unique_violation":
                return {"success": False, "error": "Email already in use"}

    Duck-typed on purpose: a plugin CANNOT import this class (importing from
    tools/ is an architecture violation — see the architecture linter), so the
    contract is "an exception carrying these attributes", which any db tool
    satisfies without plugins knowing which engine is active.

    `table`/`columns` are populated ONLY where EVERY supported engine can
    supply them: unique and NOT NULL violations. PostgreSQL DOES report the
    target of a FOREIGN KEY / CHECK failure and SQLite reports none at all
    ("FOREIGN KEY constraint failed", full stop), so this tool deliberately
    withholds it: a field that exists here and silently vanishes after a swap
    is worse than one that is always empty. The full engine detail stays in
    str(e) for logs.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unknown",
        table: str | None = None,
        columns: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.table = table
        self.columns = tuple(columns)


class DatabaseConnectionError(DatabaseError, ToolUnavailableError):
    """Connection error to the PostgreSQL server.

    Inherits ToolUnavailableError so ToolProxy marks the tool DEAD immediately
    (infrastructure failure), unlike plain DatabaseError (likely business error).
    """
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ERROR CLASSIFICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# PostgreSQL reports every integrity violation with a SQLSTATE code, which
# asyncpg exposes as `exc.sqlstate` — stable, locale-independent, and NOT the
# message text. Class 23 = integrity constraint violation.
#

_SQLSTATE_KINDS = {
    "23505": "unique_violation",
    "23503": "foreign_key_violation",
    "23502": "not_null_violation",
    "23514": "check_violation",
}

# Unique violations name the constraint, not the columns; the columns are in
# DETAIL: 'Key (email)=(ana@mail.com) already exists.'
_KEY_COLUMNS_RE = re.compile(r"Key \((?P<columns>[^)]*)\)")


def _classify_error(exc: Exception) -> dict:
    """Maps an asyncpg exception to the shared error contract.

    Returns the kwargs for DatabaseError. Anything outside the closed
    vocabulary maps to "unknown" — the contract never guesses.
    """
    kind = _SQLSTATE_KINDS.get(getattr(exc, "sqlstate", None), "unknown")

    if kind == "unique_violation":
        columns: tuple[str, ...] = ()
        match = _KEY_COLUMNS_RE.search(getattr(exc, "detail", None) or "")
        if match:
            columns = tuple(
                c.strip().strip('"') for c in match.group("columns").split(",") if c.strip()
            )
        return {"kind": kind, "table": getattr(exc, "table_name", None), "columns": columns}

    if kind == "not_null_violation":
        column = getattr(exc, "column_name", None)
        return {
            "kind": kind,
            "table": getattr(exc, "table_name", None),
            "columns": (column,) if column else (),
        }

    # foreign_key_violation / check_violation / unknown: kind only — SQLite
    # cannot report a target for these, so neither do we (see DatabaseError).
    return {"kind": kind}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRANSACTION CONTEXT MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Transaction:
    """
    Explicit transaction over a connection acquired from the pool.

    Usage:
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO ...", [...])
            await tx.execute("UPDATE ...", [...])
            rows = await tx.query("SELECT ...", [...])
        # Auto-COMMIT on block exit.
        # Auto-ROLLBACK if any exception occurs.

    The context manager handles:
    1. Acquiring a connection from the pool.
    2. Opening a real PostgreSQL transaction (BEGIN).
    3. COMMIT if everything succeeds.
    4. ROLLBACK if an exception occurs.
    5. Returning the connection to the pool ALWAYS.
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
            # If acquisition or BEGIN fails, clean up and propagate
            if self._conn is not None:
                await self._pool.release(self._conn)
                self._conn = None
            raise DatabaseConnectionError(f"Failed to start transaction: {e}") from e
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            if exc_type is None:
                # No errors → COMMIT
                await self._tx.commit()
            else:
                # Errors occurred → ROLLBACK
                await self._tx.rollback()
        finally:
            # ALWAYS return the connection to the pool
            if self._conn is not None:
                await self._pool.release(self._conn)
                self._conn = None
        # Do not suppress the exception (return False)
        return False

    # ─── API within the transaction ──────────────────────

    async def query(self, sql: str, params: list | None = None) -> list[dict]:
        """SELECT within the transaction. Returns list[dict]."""
        params = params or []
        try:
            rows = await self._conn.fetch(sql, *params)
            return [dict(row) for row in rows]
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction query failed: {e}", **_classify_error(e)) from e

    async def query_one(self, sql: str, params: list | None = None) -> dict | None:
        """SELECT a single record within the transaction. Returns dict or None."""
        params = params or []
        try:
            row = await self._conn.fetchrow(sql, *params)
            return dict(row) if row is not None else None
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction query_one failed: {e}", **_classify_error(e)) from e

    async def execute(self, sql: str, params: list | None = None) -> int | None:
        """
        INSERT/UPDATE/DELETE within the transaction.

        - If the SQL has RETURNING, returns the value of the first column
          of the first record (typically the generated ID).
        - If no RETURNING, returns the number of affected rows.
        """
        params = params or []
        try:
            # Try fetchrow first (for RETURNING)
            if "RETURNING" in sql.upper():
                row = await self._conn.fetchrow(sql, *params)
                if row is not None:
                    return row[0]
                return None
            else:
                result = await self._conn.execute(sql, *params)
                return _parse_affected_rows(result)
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Transaction execute failed: {e}", **_classify_error(e)) from e


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INTERNAL UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_affected_rows(status: str) -> int:
    """
    Parses the asyncpg status string (e.g.: 'UPDATE 3', 'DELETE 1', 'INSERT 0 1')
    and extracts the number of affected rows.
    """
    try:
        parts = status.split()
        return int(parts[-1])
    except (ValueError, IndexError):
        print(f"[PostgresqlTool] Warning: could not parse affected rows from status: {status!r}")
        return 0


# describe_schema() type vocabulary — CLOSED. See the frozen contract:
# any engine type not covered here maps to "text". No new values are added.
_TYPE_PREFIX_MAP: list[tuple[tuple[str, ...], str]] = [
    (("INT", "INTEGER", "BIGINT", "SMALLINT", "SERIAL", "BIGSERIAL"), "int"),
    (("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"), "float"),
    (("BOOL", "BOOLEAN"), "bool"),
    (("TIMESTAMP", "TIMESTAMPTZ", "DATETIME", "DATE", "TIME"), "timestamp"),
    (("JSON", "JSONB"), "json"),
    (("BLOB", "BYTEA"), "blob"),
]


def _normalize_type(engine_type: str) -> str:
    """
    Maps a PostgreSQL `information_schema.columns.data_type` value (already
    normalized by Postgres, e.g. 'character varying', 'integer',
    'timestamp with time zone') to the closed vocabulary shared with the
    SQLite tool: text/int/float/bool/timestamp/json/blob.

    Matching is by prefix, case-insensitive, after stripping any parenthetical
    (defensive — information_schema.data_type doesn't carry a "(n)" like
    SQLite's raw CREATE TABLE text does, but we normalize the same way anyway).
    Anything that doesn't match a prefix falls back to "text".
    """
    cleaned = re.sub(r"\(.*\)", "", engine_type or "").strip().upper()
    for prefixes, mapped in _TYPE_PREFIX_MAP:
        if any(cleaned.startswith(prefix) for prefix in prefixes):
            return mapped
    return "text"


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
        return "postgresql"

    # ─── CONSTRUCTOR ──────────────────────────────────────
    #
    # Configuration read only. Zero logic, zero I/O.
    # The pool is created in setup(), NOT here.
    #

    def __init__(self) -> None:
        self._host: str = os.getenv("PG_HOST", "localhost")
        self._port: int = int(os.getenv("PG_PORT", "5432"))
        self._user: str = os.getenv("PG_USER", "postgres")
        self._password: str = os.getenv("PG_PASSWORD", "")
        self._database: str = os.getenv("PG_DATABASE", "postgres")
        self._min_pool: int = int(os.getenv("PG_MIN_POOL", "1"))
        self._max_pool: int = int(os.getenv("PG_MAX_POOL", "10"))
        self._connect_timeout: float = float(os.getenv("PG_CONNECT_TIMEOUT", "5"))
        self._command_timeout: float = float(os.getenv("PG_COMMAND_TIMEOUT", "30"))
        self._pool: asyncpg.Pool | None = None

    # ─── LIFECYCLE: setup() ───────────────────────────────
    #
    # Infrastructure phase. Runs BEFORE plugins.
    # Responsibilities:
    #   1. Create the connection pool.
    #   2. Create the internal migration history table.
    #

    async def setup(self) -> None:
        print(f"[System] PostgresqlTool: Connecting to {self._host}:{self._port}/{self._database}...")

        try:
            self._pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    host=self._host,
                    port=self._port,
                    user=self._user,
                    password=self._password,
                    database=self._database,
                    min_size=self._min_pool,
                    max_size=self._max_pool,
                    timeout=self._connect_timeout,
                    command_timeout=self._command_timeout,
                ),
                timeout=self._connect_timeout,
            )
        except asyncio.TimeoutError:
            raise DatabaseConnectionError(
                f"Timeout connecting to PostgreSQL at {self._host}:{self._port}/{self._database} "
                f"(>{self._connect_timeout}s)"
            )
        except (asyncpg.PostgresError, OSError, ConnectionRefusedError) as e:
            raise DatabaseConnectionError(
                f"Cannot connect to PostgreSQL at {self._host}:{self._port}/{self._database}: {e}"
            ) from e

        # Create internal migrations table
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

        await self._run_migrations()

    # ─── MIGRATIONS: run from setup(), NOT from on_boot_complete() ──
    #
    # Responsibility: execute pending SQL migrations.
    #
    # WHY setup(): the Kernel awaits EVERY tool's setup() together
    # (asyncio.gather) before plugins boot and before any on_boot_complete
    # runs. Migrating here means anything that reads the schema afterwards —
    # a plugin in on_boot(), the manifest generator in on_boot_complete() —
    # is guaranteed to see the migrated database. In on_boot_complete the
    # order BETWEEN tools is os.walk order, i.e. a coin flip.
    # Mirrors the reference implementation (tools/sqlite/sqlite_tool.py).
    #
    # Migrations are searched in: domains/*/migrations/*.sql
    # Applied in TOPOLOGICAL ORDER based on "-- depends:" headers.
    # If no dependencies are declared, falls back to alphabetical.
    #
    # Dependency syntax (first lines of .sql file):
    #   -- depends: users/001_create_users_table
    #   -- depends: profiles/001_create_profiles_table
    #
    # Each migration runs in its own transaction.
    # If a migration fails, it is ROLLED BACK.
    #

    async def _run_migrations(self) -> None:
        # Issue 20: in production, replicas must NOT race to migrate at boot.
        # Migrations run as a pipeline step instead:
        #   DB_AUTO_MIGRATE=true uv run main.py --boot-tool db
        if os.getenv("DB_AUTO_MIGRATE", "true").strip().lower() != "true":
            print("[System] PostgresqlTool: DB_AUTO_MIGRATE=false — skipping migrations (pipeline runs `DB_AUTO_MIGRATE=true uv run main.py --boot-tool db`).")
            return
        print("[System] PostgresqlTool: Checking for pending migrations...")
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return

        # ── 1. Discover ALL migration files across all domains ──────────
        migrations = {}  # key: "domain/filename" → value: {"path": ..., "depends": [...]}
        for domain in sorted(os.listdir(domains_dir)):
            migrations_dir = os.path.join(domains_dir, domain, "migrations")
            if not os.path.isdir(migrations_dir):
                continue

            for filename in sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql")):
                key = f"{domain}/{filename}"
                filepath = os.path.join(migrations_dir, filename)

                # Parse "-- depends: domain/filename" from first lines
                depends = []
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.lower().startswith("-- depends:"):
                            dep = line.split(":", 1)[1].strip()
                            if not dep.endswith(".sql"):
                                dep += ".sql"
                            depends.append(dep)
                        elif line.startswith("--"):
                            continue  # skip other comments
                        else:
                            break  # stop parsing after first non-comment line

                migrations[key] = {"path": filepath, "depends": depends, "domain": domain, "filename": filename}

        # ── 2. Topological sort using graphlib ──────────────────────────
        from graphlib import TopologicalSorter

        graph = {}
        for key, info in migrations.items():
            graph[key] = set(info["depends"])

        try:
            sorter = TopologicalSorter(graph)
            ordered_keys = list(sorter.static_order())
        except Exception as e:
            print(f"  [Migration] ⚠️  Circular dependency detected: {e}")
            ordered_keys = sorted(migrations.keys())

        # ── 3. Apply in topological order ───────────────────────────────
        for key in ordered_keys:
            if key not in migrations:
                continue  # dependency references a migration that doesn't exist (yet)

            info = migrations[key]
            domain = info["domain"]
            filename = info["filename"]

            # Check if already applied
            already_applied = await self.query_one(
                "SELECT 1 FROM _migrations_history WHERE domain = $1 AND filename = $2",
                [domain, filename],
            )
            if already_applied:
                continue

            print(f"  [Migration] Applying {key}...")

            with open(info["path"], "r", encoding="utf-8") as f:
                lines = f.readlines()
                sql_script = "\n".join(line for line in lines if not line.strip().startswith("--"))

            # Each migration in its own transaction
            async with self.transaction() as tx:
                # asyncpg support multiple statements in execute() when no params are provided
                try:
                    await tx._conn.execute(sql_script)
                    # Register successful migration
                    await tx.execute(
                        "INSERT INTO _migrations_history (domain, filename) VALUES ($1, $2)",
                        [domain, filename],
                    )
                except Exception as e:
                    raise DatabaseError(f"Migration failed for {key}: {e}", **_classify_error(e)) from e

            print(f"  [Migration] ✅ Applied {key}")

    # ─── LIFECYCLE: shutdown() ────────────────────────────
    #
    # Closes the connection pool in an orderly manner.
    # Waits for active connections to finish.
    #

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            print("[PostgresqlTool] Connection pool closed.")

    # ─── PUBLIC API: query() ──────────────────────────────
    #
    # Executes a SELECT and returns ALL records.
    #
    # Parameters:
    #   sql:    str           — SQL query with placeholders $1, $2...
    #   params: list | None   — Values for the placeholders
    #
    # Returns: list[dict]
    #   - Empty list if no results.
    #   - Each dict has column names as keys.
    #
    # Example:
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
            raise DatabaseError(f"Query failed: {e}", **_classify_error(e)) from e

    # ─── PUBLIC API: query_one() ──────────────────────────
    #
    # Executes a SELECT and returns the FIRST record or None.
    #
    # Parameters:
    #   sql:    str           — SQL query with placeholders $1, $2...
    #   params: list | None   — Values for the placeholders
    #
    # Returns: dict | None
    #   - None if no results.
    #   - dict with keys = column names.
    #
    # Example:
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
            raise DatabaseError(f"Query failed: {e}", **_classify_error(e)) from e

    # ─── PUBLIC API: execute() ────────────────────────────
    #
    # Executes INSERT, UPDATE or DELETE.
    #
    # Parameters:
    #   sql:    str           — SQL with placeholders $1, $2...
    #   params: list | None   — Values for the placeholders
    #
    # Returns: int | None
    #   - With RETURNING: the value of the first column of the first record
    #     (typically the generated ID).
    #   - Without RETURNING: the number of affected rows (int).
    #
    # Example with RETURNING:
    #   new_id = await db.execute(
    #       "INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"]
    #   )
    #   # 42
    #
    # Example without RETURNING:
    #   affected = await db.execute(
    #       "UPDATE users SET active = $1 WHERE age < $2", [False, 18]
    #   )
    #   # 3
    #

    async def execute(self, sql: str, params: list | None = None) -> int | None:
        params = params or []
        try:
            async with self._pool.acquire() as conn:
                if re.search(r"\bRETURNING\b", sql.upper()):
                    row = await conn.fetchrow(sql, *params)
                    if row is not None:
                        return row[0]
                    return None
                else:
                    result = await conn.execute(sql, *params)
                    return _parse_affected_rows(result)
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Execute failed: {e}", **_classify_error(e)) from e

    # ─── PUBLIC API: execute_many() ───────────────────────
    #
    # Executes the same SQL statement with multiple parameter sets.
    # Internally optimized by asyncpg (pipeline).
    #
    # Parameters:
    #   sql:         str         — SQL with placeholders $1, $2...
    #   params_list: list[list]  — List of parameter lists.
    #
    # Returns: None
    #
    # Example:
    #   await db.execute_many(
    #       "INSERT INTO logs (level, msg) VALUES ($1, $2)",
    #       [["INFO", "Started"], ["ERROR", "Crashed"], ["INFO", "Recovered"]]
    #   )
    #

    async def execute_many(self, sql: str, params_list: list[list]) -> None:
        try:
            async with self._pool.acquire() as conn:
                # asyncpg.executemany expects a list of tuples
                await conn.executemany(sql, [tuple(p) for p in params_list])
        except asyncpg.PostgresError as e:
            raise DatabaseError(f"Execute many failed: {e}", **_classify_error(e)) from e

    # ─── PUBLIC API: transaction() ────────────────────────
    #
    # Opens an explicit transaction using an async context manager.
    # Within the block, all operations share the same
    # PostgreSQL connection and transaction.
    #
    # - Auto-COMMIT on block exit without errors.
    # - Auto-ROLLBACK if any exception occurs.
    # - The connection is returned to the pool ALWAYS.
    #
    # Example:
    #   async with db.transaction() as tx:
    #       user_id = await tx.execute(
    #           "INSERT INTO users (name) VALUES ($1) RETURNING id", ["Ana"]
    #       )
    #       await tx.execute(
    #           "INSERT INTO profiles (user_id, bio) VALUES ($1, $2)",
    #           [user_id, "Hello!"]
    #       )
    #   # If any execute fails, everything is rolled back.
    #

    def transaction(self) -> Transaction:
        if self._pool is None:
            raise DatabaseConnectionError("Cannot start transaction: pool is not initialized.")
        return Transaction(self._pool)

    # ─── PUBLIC API: health_check() ───────────────────────
    #
    # Verifies that the pool is active and the DB responds.
    # Useful for the Registry and monitoring.
    #
    # Returns: bool
    #   - True if the connection works.
    #   - False if there is any error.
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

    # ─── PUBLIC API: describe_schema() ────────────────────
    #
    # Live schema of the active database. Frozen contract shared with the
    # SQLite tool (tools/sqlite/sqlite_tool.py) — same migration must yield
    # the SAME dict on both engines (tests/tools/test_db_parity.py compares
    # them with `==`). Do not add keys, do not add type vocabulary values.
    #
    # Scope: schema 'public' only, table_type='BASE TABLE' only. Anything
    # not in 'public' (Postgres-owned catalog/system tables) is excluded
    # entirely — it is not "internal" to the system, it belongs to the engine.
    #
    # Returns: dict
    #   {
    #       table_name: {
    #           "internal": bool,       # True if table_name starts with "_"
    #           "columns": [
    #               {"name": str, "type": str, "nullable": bool,
    #                "default": str | None, "primary_key": bool},
    #               ...
    #           ],  # physical column order
    #           "unique": [[col, ...], ...],  # one sublist per UNIQUE constraint
    #                                          # (PK is NOT repeated here),
    #                                          # sorted by first column name
    #           "foreign_keys": [
    #               {"column": str, "references_table": str, "references_column": str},
    #               ...
    #           ],  # one entry per column; composite FKs → separate entries
    #       },
    #       ...
    #   }
    #   Tables sorted alphabetically. `type` is normalized to the closed
    #   vocabulary: text/int/float/bool/timestamp/json/blob (see _normalize_type).
    #   `default` is the literal text the engine reports, or None — never
    #   normalized, never evaluated.
    #
    # Raises: DatabaseConnectionError on any engine failure.
    #

    async def describe_schema(self) -> dict:
        try:
            tables = await self.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            schema: dict = {}
            for row in tables:
                table_name = row["table_name"]
                schema[table_name] = await self._describe_table(table_name)
            return schema
        except DatabaseError as e:
            raise DatabaseConnectionError(f"describe_schema failed: {e}") from e

    async def _describe_table(self, table_name: str) -> dict:
        """
        Internal helper for describe_schema(). Not part of the public contract —
        builds the {internal, columns, unique, foreign_keys} dict for one table.
        """
        column_rows = await self.query(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = $1 "
            "ORDER BY ordinal_position",
            [table_name],
        )

        pk_rows = await self.query(
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "    ON kcu.constraint_name = tc.constraint_name "
            "   AND kcu.table_schema = tc.table_schema "
            "WHERE tc.table_schema = 'public' AND tc.table_name = $1 "
            "  AND tc.constraint_type = 'PRIMARY KEY'",
            [table_name],
        )
        pk_columns = {r["column_name"] for r in pk_rows}

        unique_rows = await self.query(
            "SELECT tc.constraint_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "    ON kcu.constraint_name = tc.constraint_name "
            "   AND kcu.table_schema = tc.table_schema "
            "WHERE tc.table_schema = 'public' AND tc.table_name = $1 "
            "  AND tc.constraint_type = 'UNIQUE' "
            "ORDER BY tc.constraint_name, kcu.ordinal_position",
            [table_name],
        )
        unique_groups: dict[str, list[str]] = {}
        for r in unique_rows:
            unique_groups.setdefault(r["constraint_name"], []).append(r["column_name"])
        unique = sorted(unique_groups.values(), key=lambda cols: cols[0])

        # FK: table_constraints -> key_column_usage (local column) ->
        # constraint_column_usage (referenced table/column), joined on
        # constraint_name as the contract prescribes. Note: for a
        # single-column FK (the common case) this pairs local and
        # referenced column correctly. A composite FK would need ordinal
        # matching via referential_constraints to avoid a cross-join
        # between local and referenced columns; not needed for the
        # migrations this contract targets.
        fk_rows = await self.query(
            "SELECT kcu.column_name AS column_name, "
            "       ccu.table_name AS references_table, "
            "       ccu.column_name AS references_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "    ON kcu.constraint_name = tc.constraint_name "
            "   AND kcu.table_schema = tc.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "    ON ccu.constraint_name = tc.constraint_name "
            "   AND ccu.table_schema = tc.table_schema "
            "WHERE tc.table_schema = 'public' AND tc.table_name = $1 "
            "  AND tc.constraint_type = 'FOREIGN KEY' "
            "ORDER BY tc.constraint_name, kcu.ordinal_position",
            [table_name],
        )
        foreign_keys = [
            {
                "column": r["column_name"],
                "references_table": r["references_table"],
                "references_column": r["references_column"],
            }
            for r in fk_rows
        ]

        columns = [
            {
                "name": c["column_name"],
                "type": _normalize_type(c["data_type"]),
                "nullable": c["is_nullable"] == "YES",
                "default": c["column_default"],
                "primary_key": c["column_name"] in pk_columns,
            }
            for c in column_rows
        ]

        return {
            "internal": table_name.startswith("_"),
            "columns": columns,
            "unique": unique,
            "foreign_keys": foreign_keys,
        }

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
            - await describe_schema() -> dict: Live schema of the active database: {table: {internal, columns, unique, foreign_keys}}.
              Column types are normalized to a closed vocabulary (text/int/float/bool/timestamp/json/blob)
              so the same migration yields the same description on any engine.
              Tables whose name starts with "_" are marked internal; engine-owned tables are excluded.
        - EXCEPTIONS: Raises DatabaseError or DatabaseConnectionError on failure.
          Every DatabaseError carries a CLASSIFIED, engine-independent contract:
            - kind: one of unique_violation / foreign_key_violation /
              not_null_violation / check_violation / unknown (CLOSED vocabulary —
              the same values on any engine, so the swap keeps behavior).
            - table / columns: the target of the violation, filled in only where
              every engine can report it (unique and NOT NULL); FOREIGN KEY and
              CHECK carry kind only.
          Branch on the kind, NEVER on str(e) — the message text is engine-specific:
            except Exception as e:
                if getattr(e, "kind", None) == "unique_violation": ...
        - MIGRATIONS: SQL files in domains/*/migrations/*.sql are auto-applied on boot
          (topological sort). Migrations run VERBATIM (no dialect translation).
          Engine-specific SQL commits you to that engine; portable SQL
          (e.g. CURRENT_TIMESTAMP, not NOW()) keeps the SQLite <-> PostgreSQL swap free.
        """
