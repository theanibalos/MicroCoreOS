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

    readme = (Path(__file__).resolve().parent.parent.parent / "README.md").read_text(encoding="utf-8")
    documented = {n for n in CATALOG if f"`add {n}`" in readme}

    assert documented == set(CATALOG), (
        f"README's extras table is out of date — missing: {sorted(set(CATALOG) - documented)}"
    )


# ─── .env formatting and duplicate prevention ────────────────────────────────

def test_add_heads_each_extra_with_its_own_section(project):
    """.env stays readable as extras accumulate: one boxed heading per tool."""
    cli.main(["add", "postgres", "--no-install"])
    cli.main(["add", "s3", "--no-install"])

    env = (project / ".env").read_text(encoding="utf-8")

    assert "POSTGRES" in env and "microcoreos add postgres" in env
    assert "S3" in env and "microcoreos add s3" in env
    # The heading precedes the settings it introduces.
    assert env.index("microcoreos add postgres") < env.index("PG_HOST=")
    assert env.index("microcoreos add s3") < env.index("AWS_ACCESS_KEY_ID=")


def test_env_section_boxes_line_up(project):
    """Three lines of unequal width render as a broken box."""
    cli.main(["add", "postgres", "--no-install"])

    box_lines = [
        line for line in (project / ".env").read_text(encoding="utf-8").splitlines()
        if line.startswith("# ") and line[2] in "╭│╰"
    ]

    assert box_lines, "no section heading was written"
    assert len({len(line) for line in box_lines}) == 1, box_lines


def test_a_commented_setting_is_not_appended_again(project):
    """
    python-dotenv gives precedence to the LAST occurrence, so appending a
    duplicate would override the line above it and editing that line would
    silently do nothing.
    """
    (project / ".env").write_text("# PG_HOST=localhost\n#PG_PORT=5432\n", encoding="utf-8")

    cli.main(["add", "postgres", "--no-install"])

    env = (project / ".env").read_text(encoding="utf-8")
    assert env.count("PG_HOST=") == 1
    assert env.count("PG_PORT=") == 1
    assert "PG_DATABASE=microcoreos" in env  # the genuinely absent ones still land


def test_a_commented_setting_is_reported_not_decided(project, capsys):
    """
    Commenting a variable reads equally as "I want the default" and as "I will
    fill this in later". `add` cannot know which, so it says so.
    """
    (project / ".env").write_text("# PG_HOST=localhost\n", encoding="utf-8")

    cli.main(["add", "postgres", "--no-install"])

    out = capsys.readouterr().out
    assert "PG_HOST" in out and "commented out" in out


def test_a_commented_setting_does_not_block_the_rest(project):
    """Reporting one variable must not turn the whole append into a no-op."""
    (project / ".env").write_text("# SCHEDULER_ENABLED=true\n", encoding="utf-8")

    assert cli.main(["add", "scheduler", "--no-install"]) == 0

    env = (project / ".env").read_text(encoding="utf-8")
    assert env.count("SCHEDULER_ENABLED=") == 1


# ─── .env.example mirrors what `add` writes ──────────────────────────────────

def _example_sections():
    """(title, source) for every boxed heading in the shipped .env.example."""
    path = os.path.join(scaffold._template_root(), ".env.example")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return lines, [
        (i, *[p.strip() for p in line[3:-1].strip().split("  ") if p.strip()])
        for i, line in enumerate(lines) if line.startswith("# │")
    ]


def test_example_headings_come_from_the_same_generator_as_add():
    """
    The reference file and the blocks `add` appends must be the same shape.
    Hand-drawing a heading here is what makes them drift apart again.
    """
    lines, sections = _example_sections()
    assert sections, ".env.example has no boxed headings"

    for i, title, source in sections:
        expected = catalog._env_section_header(title, source)
        assert lines[i - 1: i + 2] == expected, f"heading for {title!r} is hand-drawn"


def test_every_extra_has_a_section_in_the_example():
    """A new catalog entry with no documented settings is invisible to users."""
    _, sections = _example_sections()
    documented = {source for _, _, source in sections}

    for name in catalog.CATALOG:
        if catalog.CATALOG[name].env:
            assert f"microcoreos add {name}" in documented, \
                f"{name} has env settings but no section in .env.example"


def test_every_setting_add_can_write_is_documented_in_the_example():
    """The reference is only a reference if it lists what `add` actually writes."""
    path = os.path.join(scaffold._template_root(), ".env.example")
    example = Path(path).read_text(encoding="utf-8")

    for name, extra in catalog.CATALOG.items():
        for var, _, _ in extra.env:
            assert f"{var}=" in example, f"{var} ({name}) is missing from .env.example"


def test_example_boxes_line_up():
    lines, _ = _example_sections()
    box_lines = [ln for ln in lines if ln.startswith("# ") and ln[2] in "╔║╚╭│╰"]

    assert len({len(ln) for ln in box_lines}) == 1, \
        sorted({len(ln) for ln in box_lines})
