"""The plan pipeline's commands: `migrate`, `schema`, `plan validate`, `status`.

Each one replaces a sequence an agent was previously expected to invent, and
every one of those sequences was observed failing in a real session:

  - `migrate`  — the Phase 0 step. AGENTS.md used to prescribe
    `--boot-tool db`, which boots the db tool ALONE: migrations apply, and
    the manifest is never regenerated because the context tool never runs.
    The doc claimed otherwise, so the agent trusted it, grepped a stale
    AI_CONTEXT.md for its new table, found nothing, and spent six turns
    looking for a section that could not exist yet.
  - `schema`   — verification. With no sanctioned way to see the live tables,
    the agent reached for `sqlite3` (not installed) and then for `aiosqlite`
    from the system interpreter (it lives in .venv). Two dead ends before a
    hand-written SQL probe.
  - `plan validate` — the gate. The documented form was
    `jq -Rs … | curl … | python3 -m json.tool` against a server that had to
    be running. Four turns were spent on the plumbing before the first real
    validation: an empty response (no server), a blind background boot, a
    `-d @file` JSON decode error, and finally the jq form.
  - `status`   — the preflight. Every state failure in that session (wrong
    plan active, stale manifest) was observable before the first tool call,
    and nothing was looking.

They live in the development package rather than in the `microcoreos` wheel
because none of them runs inside your application — they are things you run AT
a project while building it, which is what makes them a dev dependency that
`uv sync --no-dev` leaves out of the deploy.
"""

import asyncio
import contextlib
import os
import socket
import time

from microcoreos.base_tool import BaseTool
from microcoreos.kernel import Kernel
from microcoreos.project import (
    ensure_project_on_path,
    load_project_env,
    require_project,
)
from microcoreos.upgrade import read_manifest

from microcoreos_dev.plan import validate_yaml
from microcoreos_dev.probe import probe as _run_probe

# `plans/active_plan.yaml` is not a default anyone may override per-command:
# the whole pipeline (this module, the validator's checklist cross-check, the
# workflows, the executor prompts) is wired to that one path. A plan under any
# other name is a plan nothing will execute — which is exactly how a validated
# Twitter plan sat untouched while two sessions built the template's example
# domain instead.
PLAN_PATH = os.path.join("plans", "active_plan.yaml")
CHECKLIST_PATH = os.path.join("plans", "active_plan.md")
MANIFEST_PATH = "AI_CONTEXT.md"


@contextlib.contextmanager
def _env(**overrides: str):
    """Set env vars for the duration of one boot, then put them back.

    A command that leaves the environment changed is a command whose effect
    outlives it. The process usually exits right after, which is exactly what
    hides the bug: the moment anything else runs in the same interpreter — the
    test suite did — a later boot silently inherits `DB_AUTO_MIGRATE=false`
    from a `schema` call that only meant it for itself.
    """
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ── migrate ──────────────────────────────────────────────────────────────────

def migrate(argv: list[str]) -> int:
    """Apply migrations AND regenerate the manifest, in one offline boot.

    A full boot is the point, not an accident. The manifest is built from the
    LIVE container — every tool's interface description, every plugin the
    registry knows — so a partial boot would not merely miss the new table, it
    would overwrite AI_CONTEXT.md with a manifest describing a system that has
    no plugins and no tools. `--boot-tool db` is safe only because it never
    reaches the context tool at all.

    What `uv run main.py` cannot be here is the same boot that never returns.
    An agent running it in the foreground hangs its own session; in the
    background it has no signal for "the manifest is written" and leaves the
    process behind. This is that boot, with an ending.
    """

    if argv:
        # `migrate` takes no options, and it WRITES — to the schema and to the
        # manifest. Ignoring an argument it does not understand would turn a
        # typo, or a flag copied from an older doc, into a silent real
        # migration. Refusing costs nothing; the command has no options to miss.
        print(f"[MicroCoreOS] `migrate` takes no options (got: {argv[0]}).\n"
              "              Usage: microcoreos migrate")
        return 2

    root = ensure_project_on_path()
    if not require_project(root):
        return 2
    load_project_env(root)

    busy = _port_in_use()
    if busy:
        # A full boot binds the port, and uvicorn answers a taken one with
        # sys.exit(1) from inside its startup — killing this process mid-way
        # with a traceback about sockets, which says nothing about what to do.
        # Saying it here costs nothing and the answer is one line.
        print(f"\n[MicroCoreOS] Port {busy} is already in use — most likely "
              f"`microcoreos` or `uv run main.py` is still running.\n"
              f"              Stop it and run `microcoreos migrate` again. "
              f"(Phase 0 expects nothing booted:\n"
              f"              the plan is validated offline with "
              f"`microcoreos plan validate`.)")
        return 2

    before = _mtime(MANIFEST_PATH)


    async def _boot_once():
        kernel = Kernel()
        try:
            await kernel.boot()
        finally:
            await kernel.shutdown()

    # Deliberate override, not a default: a maintenance boot that skipped
    # migrations would not be the command that was asked for.
    with _env(DB_AUTO_MIGRATE="true"):
        asyncio.run(_boot_once())

    if not os.path.exists(MANIFEST_PATH):
        print("\n[MicroCoreOS] ⚠️  AI_CONTEXT.md was not written — is the "
              "context_manager tool present in tools/?")
        return 1
    if _mtime(MANIFEST_PATH) == before:
        print("\n[MicroCoreOS] ⚠️  AI_CONTEXT.md is unchanged on disk. "
              "Migrations may have applied, but the manifest did not regenerate.")
        return 1

    print("\n✅ Migrations applied and AI_CONTEXT.md regenerated.")
    print("   Verify the new tables with: microcoreos schema")
    return 0


def _port_in_use() -> int | None:
    """The HTTP port, if something already holds it. Read the way the tool does.

    Not a guess about which tool is installed: HTTP_HOST/HTTP_PORT are what the
    reference server reads, and a replacement claiming the name `http` reads
    the same pair. A project with no HTTP tool at all simply finds the default
    free, which is the right answer for it too.
    """

    host = os.getenv("HTTP_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("HTTP_PORT", "5000"))
    except ValueError:
        return None
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # No SO_REUSEADDR: the question is "would a bind fail right now", and
    # setting it would make this probe succeed where uvicorn's will not.
    try:
        probe.bind((host, port))
        return None
    except OSError:
        return port
    finally:
        probe.close()


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


# ── schema ───────────────────────────────────────────────────────────────────

def _open_tool(tool_name: str):
    """Find this project's `<tool_name>` tool and instantiate it. Nothing boots.

    A tool is self-contained by design — it declares its own dependencies and
    `setup()` is the whole of its startup — so running one needs no Kernel, no
    container and no other tool. What DOES need help is FINDING it: `db` is a
    name, not a class, and whether it resolves to SqliteTool or PostgresqlTool
    is the entire point of the swap story.

    Discovery is borrowed rather than reimplemented, and the borrowing is
    deliberate: `_load_modules_from_dir` imports by dotted name specifically so
    that the class it finds is the same object a plugin importing that module
    gets (path loading would make two, and `isinstance` between them is False).
    A second copy of those rules here would be a second place to get them
    subtly wrong. Constructing a Kernel boots nothing — `__init__` makes an
    empty Container and an empty dict — and reaching into a private method of a
    sibling module in the same package is the smaller cost.
    """

    for tool_cls, _ in Kernel()._load_modules_from_dir("tools", BaseTool, "_tool.py"):
        instance = tool_cls()
        if instance.name == tool_name:
            return instance
    return None


def schema(argv: list[str]) -> int:
    """Print the live schema, read from the database by the db tool itself.

    Through the tool, never around it: describe_schema() normalizes types to
    the closed vocabulary shared by every engine, so what this prints is what
    the manifest prints and what a swap must preserve. A raw sqlite3 probe
    answers a different question in a different vocabulary.

    setup() → describe_schema() → shutdown() is the entire lifecycle this
    needs. `on_boot_complete` is deliberately not called: no db driver
    implements it (both spell out that migrations run in setup(), so that
    everything downstream sees a migrated database), and the hook exists to
    hand a tool the container — which here would be empty.
    """

    root = ensure_project_on_path()
    if not require_project(root):
        return 2
    load_project_env(root)

    async def _read() -> dict:
        # Reporting, not mutating: reading the schema must never be the thing
        # that applies a migration.
        with _env(DB_AUTO_MIGRATE="false"):
            tool = _open_tool("db")
            if tool is None:
                raise LookupError("No tool named 'db' in tools/.")
            await tool.setup()
            try:
                return await tool.describe_schema()
            finally:
                await tool.shutdown()

    try:
        live = asyncio.run(_read())
    except LookupError as e:
        print(f"[MicroCoreOS] {e}")
        return 1
    except Exception as e:
        print(f"[MicroCoreOS] Could not read the schema: {e}")
        return 1

    if not live:
        print("\nNo tables. Nothing has been migrated yet.")
        return 0

    print()
    for table, info in live.items():
        label = f"{table}  (internal)" if info.get("internal") else table
        print(label)
        for column in info.get("columns", []):
            flags = []
            if column.get("primary_key"):
                flags.append("PK")
            if not column.get("nullable", True):
                flags.append("NOT NULL")
            if column.get("default") is not None:
                flags.append(f"default {column['default']}")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            print(f"    {column['name']}: {column['type']}{suffix}")
        for unique in info.get("unique", []):
            print(f"    UNIQUE({', '.join(unique)})")
        for fk in info.get("foreign_keys", []):
            print(f"    {fk['column']} → {fk['references_table']}.{fk['references_column']}")
        print()
    return 0


# ── plan validate ────────────────────────────────────────────────────────────

PLAN_USAGE = """Usage: microcoreos plan <validate|probe> [path]

  validate  the 19 rules, offline — is the PLAN well formed
  probe     drive each feature and record what it touches — does the CODE
            match the plan it was written from

  path      defaults to plans/active_plan.yaml
"""


def plan(argv: list[str]) -> int:
    if not argv or argv[0] not in ("validate", "probe"):
        print(PLAN_USAGE)
        return 2
    path = argv[1] if len(argv) > 1 else PLAN_PATH
    return _plan_validate(path) if argv[0] == "validate" else _run_probe(path)


def _plan_validate(path: str) -> int:
    """Run the 16 plan rules offline — no server, no jq, no curl.

    The validator was already pure (a Plan plus a LiveSnapshot in, violations
    out); only the snapshot needed the running system, and everything in it
    except live subscribers can be read straight off the disk. So the gate
    that the whole pipeline hangs on does not need the thing it gates.
    """

    root = ensure_project_on_path()
    if not require_project(root):
        return 2

    if not os.path.exists(path):
        print(f"[MicroCoreOS] No plan at {path}")
        return 2

    with open(path, "r", encoding="utf-8") as f:
        plan_yaml = f.read()

    checklist = None
    if os.path.exists(CHECKLIST_PATH):
        with open(CHECKLIST_PATH, "r", encoding="utf-8") as f:
            checklist = f.read()

    result, error = validate_yaml(plan_yaml, checklist=checklist)
    if error:
        print(f"\n❌ {error}\n")
        return 1

    for warning in result.warnings:
        print(f"⚠️  [rule {warning.rule}] {warning.where}: {warning.detail}")
        if warning.fix:
            print(_indent(warning.fix))
    for err in result.errors:
        print(f"❌ [rule {err.rule}] {err.where}: {err.detail}")
        if err.fix:
            print(_indent(err.fix))

    print()
    if result.valid:
        print(f"✅ {path} is valid "
              f"({len(result.warnings)} warning(s), 0 errors).")
        print("   Offline validation cannot see LIVE subscribers; a dlq_watcher "
              "or compensation consumer that exists only at runtime is\n   "
              "reported here and not by GET /system/plan/validate.")
        return 0

    print(f"❌ {path} has {len(result.errors)} error(s). "
          "Fix them in the plan — never patch around them in code.")
    return 1


def _indent(text: str) -> str:
    return "\n".join(f"      {line}" for line in text.splitlines())


# ── status ───────────────────────────────────────────────────────────────────

def status(argv: list[str]) -> int:
    """The preflight: what an agent would otherwise have to discover by failing.

    Three lines, each answering a question that silently derailed a real
    session: which plan is actually active, how much of it is done, and
    whether the manifest still describes the code on disk.
    """

    root = ensure_project_on_path()
    if not require_project(root):
        return 2

    print(f"\nMicroCoreOS project: {root}\n")
    print(f"  plan       {_plan_line()}")
    print(f"  checklist  {_checklist_line()}")
    print(f"  manifest   {_manifest_line()}")
    stray = _stray_line()
    if stray:
        print(f"  stray      {stray}")
    print()
    return 0


def _stray_line() -> str:
    """Loose .py files in the project root that the scaffold never wrote.

    Every file this pipeline produces has a declared home: `domains/` for
    plugins, models and migrations, `tools/` for infrastructure, `tests/` for
    tests. So a .py at the root came from an agent improvising — an executor
    that wrote `debug_test.py`, `debug_test2.py` and `debug_test3.py` while
    working out an import, then left them behind. Harmless individually; they
    accumulate, and the next agent reads them as project source.

    "The scaffold never wrote it" is the whole test, and it needs the
    `.microcoreos/` baseline to answer. Without one this is not a materialized
    project — it is the framework's own checkout, whose root legitimately holds
    `cli.py` and `hatch_build.py` — so the check stays quiet rather than
    inventing strays. (It flagged exactly those two before this was anchored.)

    Reported, never deleted: it is the operator's directory.
    """

    baseline = read_manifest(".")
    if baseline is None:
        return ""
    shipped = set(baseline.get("files", {}))

    strays = sorted(
        name for name in os.listdir(".")
        if name.endswith(".py") and name not in shipped
        and os.path.isfile(name)
    )
    if not strays:
        return ""
    return (", ".join(strays) + "\n             ⚠️  loose in the project root — "
            "no plan declares them. Delete them, or move\n             them "
            "under tests/ if they are worth keeping.")


def _plan_line() -> str:
    if not os.path.exists(PLAN_PATH):
        return f"MISSING — {PLAN_PATH} does not exist"
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    if _is_template(text):
        return (f"{PLAN_PATH} is STILL THE SHIPPED TEMPLATE (template: true).\n"
                "             Nothing here is your plan. Write the real one at "
                "this exact path —\n             a plan under any other name is "
                "a plan nothing will execute.")
    domain = "?"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("domain:"):
            domain = stripped.split(":", 1)[1].strip() or "?"
            break
    other = _other_plan_files()
    line = f"{PLAN_PATH} — domain `{domain}`"
    if other:
        line += ("\n             ⚠️  also present, and executed by nothing: "
                 + ", ".join(other))
    return line


def _other_plan_files() -> list[str]:
    """Plans by any other name. The pipeline reads one path and only one."""
    plans_dir = "plans"
    if not os.path.isdir(plans_dir):
        return []
    return sorted(
        os.path.join(plans_dir, name)
        for name in os.listdir(plans_dir)
        if name.endswith((".yaml", ".yml")) and name != "active_plan.yaml"
    )


def _is_template(text: str) -> bool:
    """The sentinel the shipped template carries and a real plan must not."""
    return any(
        line.strip().replace(" ", "").lower().startswith("template:true")
        for line in text.splitlines()
    )


def _checklist_line() -> str:
    if not os.path.exists(CHECKLIST_PATH):
        return f"MISSING — {CHECKLIST_PATH} does not exist"
    with open(CHECKLIST_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    if TEMPLATE_CHECKLIST_MARKER in text:
        return (f"{CHECKLIST_PATH} is STILL THE SHIPPED TEMPLATE.\n"
                "             Its tasks name no real files, so an all-[x] "
                "checklist would prove nothing.")
    done = text.count("- [x]") + text.count("- [X]")
    todo = text.count("- [ ]")
    total = done + todo
    if not total:
        return f"{CHECKLIST_PATH} — no tasks"
    return f"{done}/{total} tasks done, {todo} pending"


TEMPLATE_CHECKLIST_MARKER = "<!-- template: true -->"


def _manifest_line() -> str:
    if not os.path.exists(MANIFEST_PATH):
        return "MISSING — run: microcoreos migrate"
    manifest_at = _mtime(MANIFEST_PATH)
    newest, newest_at = _newest_source()
    age = time.time() - manifest_at
    stamp = f"regenerated {_ago(age)}"
    if newest and newest_at > manifest_at:
        return (f"STALE — {stamp}, but {newest} changed since.\n"
                "             Run: microcoreos migrate")
    return f"{stamp}, up to date with domains/ and tools/"


def _newest_source() -> tuple[str, float]:
    """The most recently touched file the manifest is supposed to describe."""
    newest, newest_at = "", 0.0
    for directory in ("domains", "tools"):
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith((".py", ".sql")):
                    continue
                path = os.path.join(root, name)
                at = _mtime(path)
                if at > newest_at:
                    newest, newest_at = path, at
    return newest, newest_at


def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


