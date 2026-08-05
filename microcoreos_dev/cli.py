"""The `microcoreos-dev` command, and the seam `microcoreos` delegates through.

Two ways into the same four commands, both deliberate:

    microcoreos plan validate       microcoreos.cli._pipeline() -> dispatch()
    microcoreos-dev plan validate   main()

`microcoreos …` is the spelling AGENTS.md, the four workflows and eight docs
use, and agents read those files as instructions — it keeps working the moment
this package is installed, so none of that corpus had to be rewritten.
`microcoreos-dev …` is what the package is actually called, and it is what
still works if the framework's CLI ever stops forwarding.

The framework imports this module lazily, from inside a function, and never at
module level. That direction is the whole point of the split: see
docs/internal/DEV_PACKAGE_SPLIT.md.
"""

import sys

from microcoreos.project import stdio_speaks_unicode

from microcoreos_dev.pipeline import migrate, plan, schema, status

COMMANDS = {
    "status": status,
    "plan": plan,
    "migrate": migrate,
    "schema": schema,
}

USAGE = """MicroCoreOS — development tooling

Usage:
  microcoreos-dev status                  Active plan, progress, manifest age
  microcoreos-dev plan validate [path]    Validate the plan offline (no server)
  microcoreos-dev plan probe [path]       Drive each feature, report what it touches
  microcoreos-dev migrate                 Apply migrations + regenerate AI_CONTEXT.md
  microcoreos-dev schema                  Print the live tables and columns

Every one of these is also reachable as `microcoreos <command>`, which is the
form the docs and workflows use. Run them from the root of a MicroCoreOS
project (the directory holding tools/, domains/ and plans/).
"""


def dispatch(name: str, argv: list[str]) -> int:
    """Run one pipeline command by name — the seam `microcoreos` calls.

    Taking a NAME rather than exporting the four functions is what keeps the
    framework's import lazy: `microcoreos.cli` needs to build its COMMANDS table
    at module level, and it can do that with a closure over a string without
    importing anything from here until the command actually runs.
    """
    command = COMMANDS.get(name)
    if command is None:
        print(f"[MicroCoreOS] `{name}` is not a pipeline command.\n")
        print(USAGE)
        return 2
    return command(argv)


def main(argv: list[str] | None = None) -> int:
    stdio_speaks_unicode()
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else 2

    return dispatch(argv[0], argv[1:])


if __name__ == "__main__":
    sys.exit(main())
