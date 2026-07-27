import sys

# The entry point lives in `microcoreos/cli.py` so the installed `microcoreos` command
# and `uv run main.py` are the exact same code path. This file stays sacred:
# it boots the Kernel and nothing else.
from microcoreos.cli import main

if __name__ == "__main__":
    sys.exit(main())
