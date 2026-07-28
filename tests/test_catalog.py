"""
`microcoreos add <extra>` — the three acts of activating an extra, in one command.

The catalog is a hand-written description of folders that live on disk, so the
first test here is that it has not drifted from them.
"""

import os
from pathlib import Path

import pytest

from microcoreos import catalog, cli, scaffold


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A materialized project, which is what `add` operates on."""
    scaffold.materialize(str(tmp_path), ai_kit=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_catalog_matches_what_is_actually_on_disk():
    """A typo in a folder name here fails silently at install time, not now."""
    root = scaffold._template_root()

    for name, extra in catalog.CATALOG.items():
        if extra.tool:
            assert os.path.isdir(os.path.join(root, "extras", "available_tools", extra.tool)), \
                f"{name}: tool folder '{extra.tool}' does not exist"
        if extra.domain:
            assert os.path.isdir(os.path.join(root, "extras", "available_domains", extra.domain)), \
                f"{name}: domain folder '{extra.domain}' does not exist"
        if extra.driver:
            assert os.path.isfile(os.path.join(
                root, "extras", "available_tools", extra.driver, f"{extra.driver}_driver.py"
            )), f"{name}: driver file for '{extra.driver}' does not exist"


def test_catalog_dependencies_are_declared_in_pyproject():
    """An extra nobody can install is worse than no extra."""
    root = scaffold._template_root()
    pyproject = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()

    for name, extra in catalog.CATALOG.items():
        if extra.dependency:
            assert f"\n{extra.dependency} = [" in pyproject, \
                f"{name}: no [project.optional-dependencies] entry '{extra.dependency}'"


def test_add_moves_tool_and_domain_and_writes_env(project):
    assert cli.main(["add", "scheduler", "--no-install"]) == 0

    assert (project / "tools" / "scheduler" / "scheduler_tool.py").is_file()
    assert (project / "domains" / "scheduler" / "plugins").is_dir()
    # Moved, not copied: the catalog must not offer it twice.
    assert not (project / "extras" / "available_tools" / "scheduler").exists()
    assert "SCHEDULER_ENABLED=true" in (project / ".env").read_text(encoding="utf-8")


def test_add_installs_a_driver_into_the_event_bus(project):
    """Transports are not tools: the file drops into tools/event_bus/."""
    assert cli.main(["add", "kafka", "--no-install"]) == 0

    assert (project / "tools" / "event_bus" / "kafka_driver.py").is_file()
    assert not (project / "tools" / "kafka").exists()
    assert "EVENT_BUS_DRIVER=kafka" in (project / ".env").read_text(encoding="utf-8")


def test_add_never_overwrites_a_setting_you_already_chose(project):
    (project / ".env").write_text("PG_PASSWORD=the-one-i-typed\n", encoding="utf-8")

    cli.main(["add", "postgres", "--no-install"])

    env = (project / ".env").read_text(encoding="utf-8")
    assert "PG_PASSWORD=the-one-i-typed" in env
    assert "PG_PASSWORD=postgres" not in env
    assert "PG_HOST=localhost" in env  # the ones that were missing still land


def test_add_is_idempotent(project):
    cli.main(["add", "postgres", "--no-install"])
    first = (project / ".env").read_text(encoding="utf-8")

    assert cli.main(["add", "postgres", "--no-install"]) == 0
    assert (project / ".env").read_text(encoding="utf-8") == first


def test_add_refuses_an_unknown_extra(project, capsys):
    assert cli.main(["add", "mongodb", "--no-install"]) == 2
    assert "Available:" in capsys.readouterr().out


def test_add_outside_a_project_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["add", "postgres", "--no-install"]) == 2
    assert "No tools/ or domains/" in capsys.readouterr().out


def test_add_never_runs_uv_without_a_pyproject(project, monkeypatch):
    """The command edits the user's pyproject and lockfile — never blind."""
    called = []
    monkeypatch.setattr(catalog.subprocess, "run", lambda *a, **k: called.append(a))
    assert not (project / "pyproject.toml").exists()

    catalog._install_dependency("postgres", str(project))
    assert called == []


def test_the_auth_placeholder_actually_boots(monkeypatch):
    """
    `add auth` writes a placeholder secret into .env, and AuthTool validates
    the secret it finds there. The first version of this entry wrote 24
    characters against a 32-character minimum: `microcoreos add auth` handed
    the user a project that died on its first boot.

    This constructs the real tool with the real placeholder rather than
    asserting a length, so it keeps holding if AuthTool's rule changes — the
    catalog's job is to write a value that WORKS, not one of a given size.
    """
    from extras.available_tools.auth.auth_tool import AuthTool
    from microcoreos.catalog import CATALOG

    for name, value, _ in CATALOG["auth"].env:
        monkeypatch.setenv(name, value)

    AuthTool()  # raises if the placeholder would not have booted


def test_the_readme_table_lists_every_extra():
    """
    The README documents each `microcoreos add` target in a table, and a table
    written by hand drifts the moment someone adds an extra — which is how the
    same README ended up claiming Python 3.10 and listing 5 of 9 extras.
    """
    from microcoreos.catalog import CATALOG

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    documented = {n for n in CATALOG if f"`add {n}`" in readme}

    assert documented == set(CATALOG), (
        f"README's extras table is out of date — missing: {sorted(set(CATALOG) - documented)}"
    )
