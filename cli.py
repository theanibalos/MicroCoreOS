import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Dev loop: `uv run cli.py` == `microcoreos dev`. Auto-reloads on .py changes.
from microcoreos.cli import dev

if __name__ == "__main__":
    sys.exit(dev(sys.argv[1:]))
