"""What the repo on disk already occupies — the offline half of `LiveSnapshot`.

The rules were always pure: only the snapshot needed the running system, and
everything in it except live SUBSCRIBERS can be read straight off the disk.
That is why `plan validate` needs no server — the gate the whole pipeline hangs
on does not need the thing it gates, which is when a plan is actually written.

The reading conventions are borrowed from the sanctioned introspection
precedents: routes by AST scan of plugin sources (the ContextTool pattern),
tables from `domains/*/migrations/*.sql`, events by AST scan of publish and
subscribe calls.
"""
import ast
import os
import re


DURABLE_DRIVERS = {"sqlite", "redis_streams", "rabbitmq", "kafka"}

CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)", re.IGNORECASE
)


class LiveSnapshot:
    """What the running system (and the repo on disk) already occupies."""

    def __init__(self, routes=None, tables=None, events=None, subscribers=None,
                 driver="in_process", columns=None):
        self.routes: dict[str, str] = routes or {}         # "METHOD /path" -> source file
        self.tables: dict[str, str] = tables or {}         # table -> owning domain
        self.columns: dict[str, set[str]] = columns or {}  # table -> its column names
        self.events: set[str] = events or set()            # events published live
        self.subscribers: dict[str, list] = subscribers or {}  # event -> handler names
        self.driver: str = driver


def scan_live_routes(domains_dir: str = "domains") -> dict[str, str]:
    """AST scan of every plugin source for add_endpoint(path, method) calls."""
    routes: dict[str, str] = {}
    if not os.path.isdir(domains_dir):
        return routes
    for domain in sorted(os.listdir(domains_dir)):
        plugins_dir = os.path.join(domains_dir, domain, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        for filename in sorted(os.listdir(plugins_dir)):
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(plugins_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr != "add_endpoint":
                    continue
                path, method = None, None
                if len(node.args) >= 2:
                    if isinstance(node.args[0], ast.Constant): path = node.args[0].value
                    if isinstance(node.args[1], ast.Constant): method = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "path" and isinstance(kw.value, ast.Constant): path = kw.value.value
                    if kw.arg == "method" and isinstance(kw.value, ast.Constant): method = kw.value.value
                if path and method:
                    routes[f"{method.upper()} {path}"] = filepath
    return routes


def scan_live_tables(domains_dir: str = "domains") -> dict[str, str]:
    """CREATE TABLE statements in every domain's migrations -> table ownership."""
    tables: dict[str, str] = {}
    if not os.path.isdir(domains_dir):
        return tables
    for domain in sorted(os.listdir(domains_dir)):
        migrations_dir = os.path.join(domains_dir, domain, "migrations")
        if not os.path.isdir(migrations_dir):
            continue
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith(".sql"):
                continue
            try:
                with open(os.path.join(migrations_dir, filename), "r", encoding="utf-8") as f:
                    sql = f.read()
            except Exception:
                continue
            for table in CREATE_TABLE_RE.findall(sql):
                tables.setdefault(table, domain)
    return tables


# A column definition starts with the column name; everything else in a CREATE
# TABLE body is a table-level constraint, which owns no name of its own.
TABLE_CONSTRAINTS = {"primary", "foreign", "unique", "check", "constraint",
                     "index", "key"}


def _strip_sql_comments(sql: str) -> str:
    """Drop -- and /* */ comments, leaving quoted literals alone.

    Quote-aware on purpose: a blind regex would treat DEFAULT '--' as the start
    of a comment and swallow the rest of the line, losing real columns — and a
    lost column becomes a false rule 16 error against a name that does exist.
    """
    out, index, quote = [], 0, ""
    while index < len(sql):
        char = sql[index]
        if quote:
            out.append(char)
            if char == quote:
                quote = ""
            index += 1
        elif char in "'\"`":
            quote = char
            out.append(char)
            index += 1
        elif sql.startswith("--", index):
            index = sql.find("\n", index)
            if index == -1:
                break
        elif sql.startswith("/*", index):
            end = sql.find("*/", index)
            index = len(sql) if end == -1 else end + 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _columns_of(sql: str, table: str) -> set[str]:
    """Column names declared in `table`'s CREATE TABLE body, if it is in `sql`."""
    sql = _strip_sql_comments(sql)
    match = re.search(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?{re.escape(table)}"
        rf"[\"'`]?\s*\(", sql, re.IGNORECASE)
    if not match:
        return set()
    depth, body_start = 0, match.end() - 1
    for index in range(body_start, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                body = sql[body_start + 1:index]
                break
    else:
        return set()                      # unbalanced parens — nothing to claim

    columns, depth, current = set(), 0, ""
    for char in body + ",":               # trailing comma flushes the last part
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:    # a comma inside DECIMAL(10,2) is not a separator
            token = current.strip().split()
            if token and token[0].strip('"\'`').lower() not in TABLE_CONSTRAINTS:
                columns.add(token[0].strip('"\'`'))
            current = ""
        else:
            current += char
    return columns


def scan_live_columns(tables: dict[str, str], domains_dir: str = "domains") -> dict[str, set[str]]:
    """table -> its declared column names, read from the owning domain's migrations."""
    columns: dict[str, set[str]] = {}
    for table, domain in tables.items():
        migrations_dir = os.path.join(domains_dir, domain, "migrations")
        if not os.path.isdir(migrations_dir):
            continue
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith(".sql"):
                continue
            try:
                with open(os.path.join(migrations_dir, filename), "r", encoding="utf-8") as f:
                    found = _columns_of(f.read(), table)
            except Exception:
                continue
            if found:
                columns.setdefault(table, set()).update(found)
    return columns
def scan_live_events(domains_dir: str = "domains") -> tuple[set[str], dict[str, list[str]]]:
    """(published events, event -> ["Class.method"]) by AST, for offline use.

    The endpoint reads both from the live bus, which is strictly better —
    it sees what actually registered. This is the offline stand-in, and it is
    the difference between rule 3 being useful before boot and rule 3 flagging
    every event the existing domains already publish.
    """
    published: set[str] = set()
    subscribers: dict[str, list[str]] = {}
    if not os.path.isdir(domains_dir):
        return published, subscribers
    for domain in sorted(os.listdir(domains_dir)):
        plugins_dir = os.path.join(domains_dir, domain, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        for filename in sorted(os.listdir(plugins_dir)):
            if not filename.endswith(".py"):
                continue
            try:
                with open(os.path.join(plugins_dir, filename), "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue
            for klass in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                for node in ast.walk(klass):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.args
                            and isinstance(node.args[0], ast.Constant)
                            and isinstance(node.args[0].value, str)):
                        continue
                    event = node.args[0].value
                    if node.func.attr == "publish":
                        published.add(event)
                    elif node.func.attr == "subscribe":
                        handler = "handler"
                        if len(node.args) > 1 and isinstance(node.args[1], ast.Attribute):
                            handler = node.args[1].attr
                        subscribers.setdefault(event, []).append(f"{klass.name}.{handler}")
    return published, subscribers


def offline_snapshot(domains_dir: str = "domains") -> LiveSnapshot:
    """What the repo on disk already occupies, with no system running."""
    tables = scan_live_tables(domains_dir)
    published, subscribers = scan_live_events(domains_dir)
    return LiveSnapshot(
        routes=scan_live_routes(domains_dir),
        tables=tables,
        columns=scan_live_columns(tables, domains_dir),
        events=published | set(subscribers),
        subscribers=subscribers,
        driver=os.getenv("EVENT_BUS_DRIVER", "in_process"),
    )
