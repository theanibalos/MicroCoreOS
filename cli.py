import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from watchfiles import run_process
from main import main as _main

if __name__ == "__main__":
    run_process(
        ".",
        target=_main,
        watch_filter=lambda change, path: path.endswith(".py") and "__pycache__" not in path
    )