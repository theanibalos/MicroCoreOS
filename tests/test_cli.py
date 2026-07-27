"""
The packaged entry point (`microcoreos`, installed from the wheel).

These are the checks that the console script behaves like `uv run main.py`
even though it starts from a completely different sys.path.
"""

import os
import sys

from microcoreos import cli


def test_help_exits_zero(capsys):
    assert cli.main(["--help"]) == 0
    assert "microcoreos" in capsys.readouterr().out


def test_unknown_command_exits_two(capsys):
    assert cli.main(["frobnicate"]) == 2
    assert "Unknown command" in capsys.readouterr().out


def test_run_outside_a_project_refuses_to_boot(tmp_path, monkeypatch, capsys):
    """
    Without tools/ or domains/ the Kernel discovers nothing and announces
    "System Ready" — so the CLI must catch the wrong-directory case first.
    """
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 2
    assert "No tools/ or domains/" in capsys.readouterr().out


def test_ensure_project_on_path_puts_cwd_first(tmp_path, monkeypatch):
    """
    `python main.py` gets the project root on sys.path for free; an installed
    console script does not — without this the Kernel cannot import `tools.*`.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(tmp_path)])

    root = cli._ensure_project_on_path()

    assert root == os.getcwd()
    assert sys.path[0] == root


def test_looks_like_a_project(tmp_path):
    assert not cli._looks_like_a_project(str(tmp_path))
    (tmp_path / "domains").mkdir()
    assert cli._looks_like_a_project(str(tmp_path))


def test_boot_tool_without_a_name_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()
    assert cli.main(["run", "--boot-tool"]) == 2
    assert "--boot-tool <tool_name>" in capsys.readouterr().out


def test_dev_without_watchfiles_reports_how_to_install(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "watchfiles", None)
    assert cli.main(["dev"]) == 1
    assert "uv add --dev watchfiles" in capsys.readouterr().out


def test_env_is_loaded_from_the_project_not_from_the_package(tmp_path, monkeypatch):
    """
    Bare `load_dotenv()` searches upward from its CALLER — which, installed, is
    site-packages. The project's .env must be loaded by explicit path or a
    scaffolded project boots with `AUTH_SECRET_KEY is required` despite having
    one.
    """
    monkeypatch.delenv("MICROCOREOS_ENV_PROBE", raising=False)
    (tmp_path / ".env").write_text("MICROCOREOS_ENV_PROBE=from-the-project\n")

    cli._load_project_env(str(tmp_path))

    assert os.environ["MICROCOREOS_ENV_PROBE"] == "from-the-project"
    monkeypatch.delenv("MICROCOREOS_ENV_PROBE", raising=False)
