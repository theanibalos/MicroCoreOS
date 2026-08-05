"""
The `microcoreos` command — the entry point installed by the wheel.

It lives inside the package on purpose. A top-level `cli.py` / `main.py` cannot
ship: dropped in site-packages they would collide with the user's own root
files, the same shadowing problem that forces the `core` rename (Issue 39).
The root `main.py` and `cli.py` are thin shims over this module, so
`uv run main.py` keeps working inside a project.

    microcoreos new my-app          materialize a new project's source
    microcoreos add postgres        install an extra: dependency + folders + .env
    microcoreos upgrade             what changed upstream since you scaffolded
    microcoreos                     boot the Kernel (same as `uv run main.py`)
    microcoreos run                 idem, explicit
    microcoreos run --boot-tool db  boot ONE tool in isolation and exit
    microcoreos dev                 boot with auto-reload on .py changes
    microcoreos status              preflight: active plan, progress, manifest age
    microcoreos plan validate       run the plan rules offline
    microcoreos migrate             apply migrations + regenerate AI_CONTEXT.md
    microcoreos schema              print the live tables and columns
"""

import sys
import signal
import asyncio

from microcoreos.kernel import Kernel
from microcoreos.catalog import add
from microcoreos.scaffold import new
from microcoreos.upgrade import upgrade

from microcoreos.project import (
    ensure_project_on_path,
    load_project_env,
    require_project,
    stdio_speaks_unicode,
)

USAGE = """MicroCoreOS

Usage:
  microcoreos new <path> [--force] [--no-ai-kit]  Materialize a new project
  microcoreos add <extra> [--no-install]          Install an extra completely
  microcoreos upgrade [--apply]                   Report/apply upstream changes
  microcoreos [run] [--boot-tool <tool_name>]     Boot the Kernel in this directory
  microcoreos dev                                 Boot with auto-reload on .py changes

The plan pipeline (docs/PARALLEL_DEVELOPMENT.md):
  microcoreos status                              Active plan, progress, manifest age
  microcoreos plan validate [path]                Validate the plan offline (no server)
  microcoreos migrate                             Apply migrations + regenerate AI_CONTEXT.md
  microcoreos schema                              Print the live tables and columns

Except for `new`, run these from the root of a MicroCoreOS project (the
directory holding tools/, domains/ and plans/).
"""


async def _boot_forever():
    stop_event = asyncio.Event()
    app = Kernel()

    def stop_signal_handler():
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_signal_handler)

    try:
        await app.boot()
        print("\n🚀 [MicroCoreOS] System Online. (Ctrl+C to exit)")
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.shutdown()
        print("[MicroCoreOS] Shutdown complete. See you soon!")


def run(argv: list[str]) -> int:
    """Boot the Kernel. With --boot-tool, boot ONE tool in isolation and exit."""
    stdio_speaks_unicode()  # Reached without `main` as the reload child of `dev`.
    root = ensure_project_on_path()
    # The Kernel would otherwise discover nothing and announce "System Ready" —
    # the most confusing possible answer to being in the wrong directory.
    if not require_project(root):
        return 2

    if "--boot-tool" in argv:
        # Pipeline mode: which tool and with which env vars is deployment
        # configuration, not code here.
        idx = argv.index("--boot-tool")
        if idx + 1 >= len(argv):
            print("Usage: microcoreos run --boot-tool <tool_name>")
            return 2
        load_project_env(root)
        asyncio.run(Kernel().boot_tool(argv[idx + 1]))
        return 0

    load_project_env(root)

    try:
        asyncio.run(_boot_forever())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


def _watch_python_sources(change, path: str) -> bool:
    """Which file changes trigger a reload. Module level so it can be pickled."""
    return path.endswith(".py") and "__pycache__" not in path


def dev(argv: list[str]) -> int:
    """Boot with auto-reload. watchfiles is a dev dependency, hence the lazy import."""
    stdio_speaks_unicode()  # Reached without `main` as the root `cli.py` shim.
    try:
        from watchfiles import run_process
    except ImportError:
        print(
            "[MicroCoreOS] `microcoreos dev` needs watchfiles.\n"
            "               Install it with: uv add --dev watchfiles"
        )
        return 1

    # The project root — not the package — is what gets watched and booted.
    root = ensure_project_on_path()

    # Everything handed to run_process must survive pickling: watchfiles starts
    # the child with multiprocessing's SPAWN method, which serializes the target
    # rather than inheriting it. Two lambdas defined right here used to sit in
    # this call, and `microcoreos dev` died on every invocation with
    # "Can't get local object 'dev.<locals>.<lambda>'". Module-level names
    # pickle by reference; local ones cannot pickle at all.
    run_process(
        root,
        target=run,
        args=(argv,),
        watch_filter=_watch_python_sources,
    )
    return 0


# The plan pipeline ships separately now, as `microcoreos-dev`. The commands
# keep the names they always had: AGENTS.md, four workflows and eight docs spell
# them this way, and agents read those files as instructions. Renaming them
# would mean rewriting that corpus for nothing. See docs/internal/DEV_PACKAGE_SPLIT.md.
PIPELINE_COMMANDS = ("status", "plan", "migrate", "schema")

MISSING_DEV_PACKAGE = """\
[MicroCoreOS] `microcoreos {name}` lives in the development package.

              Install it:  uv add --dev microcoreos-dev

              It is a dev dependency because validating a plan, applying
              migrations and reading the schema are things you do WHILE
              building — never inside a running app. That is also why
              `uv sync --no-dev` leaves it out of your deploy."""


def _pipeline(name: str):
    """Hand one pipeline command to `microcoreos-dev`, if it is installed.

    The import sits INSIDE the returned function, and that placement is the rule
    the whole split exists to establish: `microcoreos` must not depend on
    `microcoreos_dev`. Hoisting it to module level would make the framework
    require its own development tooling in order to start — the same inverted
    direction as the old `pipeline.py` importing the project's vendored
    validator, aimed at a different victim. `tests/core/test_core_purity.py` fails
    if it ever moves up there.
    """
    def command(argv: list[str]) -> int:
        try:
            from microcoreos_dev.cli import dispatch
        except ImportError:
            print(MISSING_DEV_PACKAGE.format(name=name))
            return 2
        return dispatch(name, argv)

    command.__name__ = name
    return command


COMMANDS = {
    "new": new, "add": add, "upgrade": upgrade, "run": run, "dev": dev,
    **{name: _pipeline(name) for name in PIPELINE_COMMANDS},
}


def main(argv: list[str] | None = None) -> int:
    stdio_speaks_unicode()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    command = run
    if argv and not argv[0].startswith("-"):
        if argv[0] not in COMMANDS:
            print(f"[MicroCoreOS] Unknown command: {argv[0]}\n")
            print(USAGE)
            return 2
        command = COMMANDS[argv.pop(0)]

    return command(argv)


if __name__ == "__main__":
    sys.exit(main())
