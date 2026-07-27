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
"""

import os
import sys
import signal
import asyncio

from dotenv import load_dotenv

from microcoreos.kernel import Kernel
from microcoreos.catalog import add
from microcoreos.scaffold import new
from microcoreos.upgrade import upgrade

USAGE = """MicroCoreOS

Usage:
  microcoreos new <path> [--force] [--no-ai-kit]  Materialize a new project
  microcoreos add <extra> [--no-install]          Install an extra completely
  microcoreos upgrade [--apply]                   Report/apply upstream changes
  microcoreos [run] [--boot-tool <tool_name>]     Boot the Kernel in this directory
  microcoreos dev                                 Boot with auto-reload on .py changes

Except for `new`, run these from the root of a MicroCoreOS project (the
directory holding tools/, domains/ and plans/).
"""


def _load_project_env(root: str) -> None:
    """
    Load `<project>/.env` — explicitly, by path.

    Bare `load_dotenv()` searches upward from the file that CALLS it. Inside a
    checkout that file was the root `main.py`, so it landed on the project's
    .env by accident. Installed, the caller is `site-packages/microcoreos/
    cli.py` and the search walks up the venv instead: the project's .env is
    never seen, and the failure surfaces far away as `AUTH_SECRET_KEY is
    required` on a project that has one.
    """
    load_dotenv(os.path.join(root, ".env"))


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


def _ensure_project_on_path() -> str:
    """
    Put the project root (the CWD) at the front of sys.path and return it.

    `python main.py` gets this for free — sys.path[0] is the script's directory.
    An installed console script does NOT: sys.path[0] is the venv's bin/, so
    every `importlib.import_module("tools.sqlite.sqlite_tool")` the Kernel does
    fails with "No module named 'tools'". Without this, `microcoreos` boots an
    empty system and reports it as Ready.
    """
    root = os.getcwd()
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _looks_like_a_project(root: str) -> bool:
    """A MicroCoreOS project is a directory holding tools/ and/or domains/."""
    return any(os.path.isdir(os.path.join(root, d)) for d in ("tools", "domains"))


def run(argv: list[str]) -> int:
    """Boot the Kernel. With --boot-tool, boot ONE tool in isolation and exit."""
    _stdio_speaks_unicode()  # Reached without `main` as the reload child of `dev`.
    root = _ensure_project_on_path()
    if not _looks_like_a_project(root):
        # The Kernel would otherwise discover nothing and announce "System
        # Ready" — the most confusing possible answer to being in the wrong
        # directory.
        print(
            f"[MicroCoreOS] No tools/ or domains/ directory in {root}.\n"
            "              Run this from the root of a MicroCoreOS project."
        )
        return 2

    if "--boot-tool" in argv:
        # Pipeline mode: which tool and with which env vars is deployment
        # configuration, not code here.
        idx = argv.index("--boot-tool")
        if idx + 1 >= len(argv):
            print("Usage: microcoreos run --boot-tool <tool_name>")
            return 2
        _load_project_env(root)
        asyncio.run(Kernel().boot_tool(argv[idx + 1]))
        return 0

    _load_project_env(root)

    try:
        asyncio.run(_boot_forever())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


def dev(argv: list[str]) -> int:
    """Boot with auto-reload. watchfiles is a dev dependency, hence the lazy import."""
    _stdio_speaks_unicode()  # Reached without `main` as the root `cli.py` shim.
    try:
        from watchfiles import run_process
    except ImportError:
        print(
            "[MicroCoreOS] `microcoreos dev` needs watchfiles.\n"
            "               Install it with: uv add --dev watchfiles"
        )
        return 1

    # The project root — not the package — is what gets watched and booted.
    root = _ensure_project_on_path()

    run_process(
        root,
        target=lambda: run(argv),
        watch_filter=lambda change, path: path.endswith(".py") and "__pycache__" not in path,
    )
    return 0


COMMANDS = {"new": new, "add": add, "upgrade": upgrade, "run": run, "dev": dev}


def _stdio_speaks_unicode() -> None:
    """Every message this CLI prints contains an emoji or an em dash.

    On Windows that is not decoration, it is a crash: when stdout is a pipe or a
    file rather than a console, Python encodes it as cp1252 and `print("✅")`
    raises UnicodeEncodeError before the command does any work. Redirecting
    output is exactly what CI, `| tee` and editors' terminals do.

    A real Windows console already reports utf-8, so this is a no-op there and
    everywhere on Linux and macOS. `backslashreplace` is the belt to the braces:
    whatever the stream turns out to be, printing must never be the thing that
    fails.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "").replace("_", "") == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass  # Not a reconfigurable text stream; nothing to do but try.


def main(argv: list[str] | None = None) -> int:
    _stdio_speaks_unicode()
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
