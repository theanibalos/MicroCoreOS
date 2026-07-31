"""Locating and preparing the project a command is being run AT.

Four helpers, shared by `microcoreos` and by `microcoreos-dev`. They lived in
`cli.py` as private names, which was fine while the only caller was in the same
wheel. It stopped being fine when the plan pipeline moved out: reaching for
`microcoreos.cli._require_project` across a distribution boundary is a private
dependency between two packages that ship and version separately — a milder
form of the inversion the split exists to remove, and the kind that erodes
quietly because nothing about it fails today.

So this is the seam, stated: what the development package is allowed to use.
`cli.py` re-exports the names it always had, so nothing that imported them from
there had to change.
"""

import os
import sys

from dotenv import load_dotenv


def ensure_project_on_path() -> str:
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


def load_project_env(root: str) -> None:
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


def looks_like_a_project(root: str) -> bool:
    """A MicroCoreOS project is a directory holding tools/ and/or domains/."""
    return any(os.path.isdir(os.path.join(root, d)) for d in ("tools", "domains"))


def require_project(root: str) -> bool:
    """Same guard as `run`, shared with the pipeline commands.

    Being in the wrong directory must never look like an empty project: the
    Kernel would discover nothing and report "System Ready", and `status`
    would report a pristine plan that is really someone else's directory.
    """
    if looks_like_a_project(root):
        return True
    print(
        f"[MicroCoreOS] No tools/ or domains/ directory in {root}.\n"
        "              Run this from the root of a MicroCoreOS project."
    )
    return False


def stdio_speaks_unicode() -> None:
    """Every message either CLI prints contains an emoji or an em dash.

    On Windows that is not decoration, it is a crash: when stdout is a pipe or a
    file rather than a console, Python encodes it as cp1252 and `print("✅")`
    raises UnicodeEncodeError before the command does any work. Redirecting
    output is exactly what CI, `| tee` and editors' terminals do.

    A real Windows console already reports utf-8, so this is a no-op there and
    everywhere on Linux and macOS. `backslashreplace` is the belt to the braces:
    whatever the stream turns out to be, printing must never be the thing that
    fails.

    Here rather than in `cli.py` because `microcoreos-dev` has its own entry
    point and prints the same characters — the ✅ and ❌ of `plan validate` are
    the most redirected output either command produces.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "").replace("_", "") == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass  # Not a reconfigurable text stream; nothing to do but try.
