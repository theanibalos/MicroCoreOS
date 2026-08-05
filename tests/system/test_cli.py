"""
The packaged entry point (`microcoreos`, installed from the wheel).

These are the checks that the console script behaves like `uv run main.py`
even though it starts from a completely different sys.path.
"""

import io
import os
import pickle
import sys
import types

from microcoreos import cli, project


def test_help_exits_zero(capsys):
    assert cli.main(["--help"]) == 0
    assert "microcoreos" in capsys.readouterr().out


def test_it_prints_emoji_to_a_cp1252_stream(tmp_path, monkeypatch):
    """
    Windows encodes a redirected stdout as cp1252, and this CLI's success
    messages are full of emoji and em dashes. Before `main` reconfigured the
    stream, `microcoreos new` raised UnicodeEncodeError on its own last line —
    every time its output was piped, which is what CI does.
    """
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))

    assert cli.main(["new", str(tmp_path / "app"), "--no-ai-kit"]) == 0

    sys.stdout.flush()
    assert "✅" in raw.getvalue().decode("utf-8")


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

    root = project.ensure_project_on_path()

    assert root == os.getcwd()
    assert sys.path[0] == root


def test_looks_like_a_project(tmp_path):
    assert not project.looks_like_a_project(str(tmp_path))
    (tmp_path / "domains").mkdir()
    assert project.looks_like_a_project(str(tmp_path))


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
    (tmp_path / ".env").write_text("MICROCOREOS_ENV_PROBE=from-the-project\n", encoding="utf-8")

    project.load_project_env(str(tmp_path))

    assert os.environ["MICROCOREOS_ENV_PROBE"] == "from-the-project"
    monkeypatch.delenv("MICROCOREOS_ENV_PROBE", raising=False)


def test_dev_hands_watchfiles_only_picklable_things(tmp_path, monkeypatch):
    """
    watchfiles starts the reload child with multiprocessing's spawn method, so
    everything it receives is pickled. `dev` used to pass two lambdas defined
    inside itself and died on every single run with "Can't get local object
    'dev.<locals>.<lambda>'" — the command was broken from the moment it
    shipped, and the only test it had covered the missing-watchfiles path.

    Pickling is the assertion because unpicklable is exactly what was wrong.
    """
    captured = {}

    def fake_run_process(root, target=None, args=(), watch_filter=None, **kwargs):
        captured.update(root=root, target=target, args=args, watch_filter=watch_filter)

    monkeypatch.setitem(
        sys.modules, "watchfiles", types.SimpleNamespace(run_process=fake_run_process)
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()

    assert cli.dev([]) == 0

    pickle.dumps(captured["target"])
    pickle.dumps(captured["watch_filter"])
    pickle.dumps(captured["args"])

    # And the filter still filters: sources reload, bytecode does not.
    assert captured["watch_filter"](None, "domains/orders/plugins/x_plugin.py")
    assert not captured["watch_filter"](None, "domains/orders/__pycache__/x.pyc")



# ── Delegation to the development package ───────────────────────────────────
#
# `status`, `plan`, `migrate` and `schema` ship in `microcoreos-dev` now, but
# they answer to the same names they always had, because AGENTS.md, the four
# workflows and eight docs spell them that way and agents read those files as
# instructions. What the framework keeps is the dispatch and the USAGE text;
# what the commands DO is tested in tests/dev/test_pipeline.py.


def test_the_pipeline_commands_are_registered():
    for name in ("status", "plan", "migrate", "schema"):
        assert name in cli.COMMANDS


def test_help_mentions_every_pipeline_command(capsys):
    cli.main(["--help"])
    out = capsys.readouterr().out
    for name in ("status", "plan validate", "migrate", "schema"):
        assert name in out


def test_the_delegation_import_is_not_at_module_level():
    """The framework must import and boot with no development package present.

    Not a style preference: a production install runs `uv sync --no-dev`, so
    `microcoreos_dev` is genuinely absent there. A module-level import would
    make `import microcoreos.cli` — and therefore every `microcoreos run` —
    fail outright on exactly the deploy this split exists to keep clean.

    tests/core/test_core_purity.py asserts the same thing statically, across the
    whole package. This one proves the runtime consequence.
    """
    import importlib
    from importlib.abc import MetaPathFinder

    class _Blocked(MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "microcoreos_dev":
                raise ImportError(f"blocked for this test: {name}")
            return None

    blocker = _Blocked()
    sys.meta_path.insert(0, blocker)
    saved = {n: m for n, m in sys.modules.items() if n.startswith("microcoreos")}
    try:
        for name in list(saved):
            del sys.modules[name]
        reloaded = importlib.import_module("microcoreos.cli")
        assert "status" in reloaded.COMMANDS
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)


def test_a_pipeline_command_without_the_dev_package_says_how_to_install_it(capsys):
    """The failure a user actually meets: the command exists, the package does not.

    An ImportError traceback here would be the worst possible answer — it names
    a module the user has never heard of, for a command the help text told them
    to run.
    """
    from importlib.abc import MetaPathFinder

    class _Blocked(MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "microcoreos_dev":
                raise ImportError(f"blocked for this test: {name}")
            return None

    blocker = _Blocked()
    sys.meta_path.insert(0, blocker)
    saved = {n: m for n, m in sys.modules.items() if n.startswith("microcoreos_dev")}
    try:
        for name in list(saved):
            del sys.modules[name]
        assert cli.main(["plan", "validate"]) == 2
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)

    out = capsys.readouterr().out
    assert "uv add --dev microcoreos-dev" in out
    assert "Traceback" not in out
