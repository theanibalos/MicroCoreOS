"""
`microcoreos upgrade` — telling YOUR edits apart from a stale file.

The whole value is the three-way comparison (local / baseline / upstream).
Every test here is about a case where getting it wrong would either destroy
someone's work or silently leave them on an old file.
"""

import json
import os
import shutil

import pytest

from microcoreos import cli, scaffold, upgrade


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A scaffolded project plus a private copy of the template to 'release'."""
    root = tmp_path / "app"
    root.mkdir()
    cli.main(["new", str(root), "--no-ai-kit"])

    # A stand-in for the next published version, so a test can move upstream.
    template = tmp_path / "upstream"
    shutil.copytree(scaffold._template_root(), template,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".venv", "*.db"))
    monkeypatch.setattr(scaffold, "_template_root", lambda: str(template))
    monkeypatch.chdir(root)
    return root, template


def test_new_records_a_baseline(project):
    root, _ = project
    manifest = json.load(open(root / ".microcoreos" / "manifest.json"))

    assert "tools/sqlite/sqlite_tool.py" in manifest["files"]
    assert len(manifest["files"][ "tools/sqlite/sqlite_tool.py"]) == 64  # sha256 hex
    assert "__pycache__" not in json.dumps(manifest)


def test_untouched_file_is_safe_to_update(project):
    root, template = project
    (template / "tools" / "sqlite" / "sqlite_tool.py").write_text("# upstream fix\n")

    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"])

    assert "tools/sqlite/sqlite_tool.py" in report["update"]
    assert report["conflict"] == []


def test_your_edit_is_never_offered_for_update(project):
    """Upstream is quiet, you changed it — there is nothing to do, ever."""
    root, _ = project
    (root / "tools" / "sqlite" / "sqlite_tool.py").write_text("# my fix\n")

    report = upgrade.classify(str(root), scaffold._template_root(),
                              upgrade.read_manifest(str(root))["files"])

    assert "tools/sqlite/sqlite_tool.py" in report["yours"]
    assert "tools/sqlite/sqlite_tool.py" not in report["update"]


def test_both_changed_is_a_conflict_and_is_left_alone(project):
    root, template = project
    (root / "tools" / "sqlite" / "sqlite_tool.py").write_text("# my fix\n")
    (template / "tools" / "sqlite" / "sqlite_tool.py").write_text("# upstream fix\n")

    assert cli.main(["upgrade", "--apply"]) == 0

    # The user's work survived an --apply that touched other files.
    assert (root / "tools" / "sqlite" / "sqlite_tool.py").read_text() == "# my fix\n"


def test_apply_writes_the_safe_ones_and_moves_the_baseline(project):
    root, template = project
    (template / "tools" / "sqlite" / "sqlite_tool.py").write_text("# upstream fix\n")

    assert cli.main(["upgrade", "--apply"]) == 0
    assert (root / "tools" / "sqlite" / "sqlite_tool.py").read_text() == "# upstream fix\n"

    # Baseline moved with it: a second run has nothing left to do.
    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"])
    assert report["update"] == []


def test_a_file_you_deleted_is_not_resurrected(project):
    """Deleting a tool you do not use is a supported act, not damage."""
    root, _ = project
    shutil.rmtree(root / "tools" / "scheduler", ignore_errors=True)
    os.remove(root / "tools" / "state" / "state_tool.py")

    cli.main(["upgrade", "--apply"])
    assert not (root / "tools" / "state" / "state_tool.py").exists()


def test_genuinely_new_upstream_file_is_offered(project):
    root, template = project
    (template / "tools" / "brandnew").mkdir()
    (template / "tools" / "brandnew" / "brandnew_tool.py").write_text("# new\n")

    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"])
    assert "tools/brandnew/brandnew_tool.py" in report["new"]


def test_without_a_manifest_it_refuses(project, capsys):
    """The baseline is written by `new`; its absence is an error, not a mode."""
    root, template = project
    shutil.rmtree(root / ".microcoreos")
    (template / "tools" / "sqlite" / "sqlite_tool.py").write_text("# upstream fix\n")
    before = (root / "tools" / "sqlite" / "sqlite_tool.py").read_text()

    assert cli.main(["upgrade", "--apply"]) == 1

    assert "No .microcoreos/manifest.json" in capsys.readouterr().out
    assert (root / "tools" / "sqlite" / "sqlite_tool.py").read_text() == before


def test_upgrade_outside_a_project_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["upgrade"]) == 2
    assert "No tools/ or domains/" in capsys.readouterr().out


def test_a_manifest_from_an_older_format_still_reads(project):
    """The manifest is a published format now: missing keys must not crash."""
    root, template = project
    path = root / ".microcoreos" / "manifest.json"
    old = json.load(open(path))
    old.pop("moved", None)
    json.dump({"version": old["version"], "files": old["files"]}, open(path, "w"))

    (template / "tools" / "sqlite" / "sqlite_tool.py").write_text("# upstream\n")
    assert cli.main(["upgrade"]) == 0


def test_apply_does_not_turn_an_unresolved_conflict_into_a_safe_update(project):
    """
    The baseline may only advance for files actually written. Recomputing it
    from disk would record the user's conflicted file as 'never edited', and
    the next --apply would overwrite the edit this run refused to touch.
    """
    root, template = project
    (root / "tools" / "logger" / "logger_tool.py").write_text("# my patch\n")
    (template / "tools" / "logger" / "logger_tool.py").write_text("# upstream\n")
    (template / "tools" / "state" / "state_tool.py").write_text("# upstream\n")

    cli.main(["upgrade", "--apply"])          # writes state, refuses logger
    cli.main(["upgrade", "--apply"])          # must STILL refuse logger

    assert (root / "tools" / "logger" / "logger_tool.py").read_text() == "# my patch\n"
    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"])
    assert "tools/logger/logger_tool.py" in report["conflict"]
    assert report["update"] == []


def test_an_extra_you_installed_still_receives_upstream_fixes(project):
    """
    `microcoreos add` moves a folder out of extras/. The baseline is keyed by
    UPSTREAM path, so without the recorded move an upgrade would look for the
    tool where it no longer is and silently skip the infrastructure the user
    deliberately installed.
    """
    root, template = project
    assert cli.main(["add", "scheduler", "--no-install"]) == 0
    assert (root / "tools" / "scheduler" / "scheduler_tool.py").is_file()

    upstream_file = template / "extras" / "available_tools" / "scheduler" / "scheduler_tool.py"
    upstream_file.write_text("# upstream fix\n")

    assert cli.main(["upgrade", "--apply"]) == 0
    # The fix landed where the tool actually lives now.
    assert (root / "tools" / "scheduler" / "scheduler_tool.py").read_text() == "# upstream fix\n"


def test_a_driver_you_installed_is_tracked_to_its_new_home(project):
    root, template = project
    cli.main(["add", "kafka", "--no-install"])

    (template / "extras" / "available_tools" / "kafka" / "kafka_driver.py").write_text("# fix\n")
    cli.main(["upgrade", "--apply"])

    assert (root / "tools" / "event_bus" / "kafka_driver.py").read_text() == "# fix\n"


def test_an_extra_you_moved_BY_HAND_still_receives_fixes(project):
    """
    The docs present `mv extras/... tools/` as the manual equivalent of
    `microcoreos add`, and it leaves no record. Without the conventional-
    destination fallback upgrade reported "everything is current" while the
    fix never arrived — wrong, and silently so.
    """
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "postgresql"))

    upstream = template / "extras" / "available_tools" / "postgresql" / "postgresql_tool.py"
    upstream.write_text("# upstream fix\n")

    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"])
    assert "extras/available_tools/postgresql/postgresql_tool.py" in report["update"]

    assert cli.main(["upgrade", "--apply"]) == 0
    assert (root / "tools" / "postgresql" / "postgresql_tool.py").read_text() == "# upstream fix\n"
    # Written where it lives, not recreated back in extras/.
    assert not (root / "extras" / "available_tools" / "postgresql").exists()


def test_a_driver_moved_by_hand_is_found_in_the_event_bus(project):
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "kafka" / "kafka_driver.py"),
                str(root / "tools" / "event_bus" / "kafka_driver.py"))

    (template / "extras" / "available_tools" / "kafka" / "kafka_driver.py").write_text("# fix\n")
    cli.main(["upgrade", "--apply"])

    assert (root / "tools" / "event_bus" / "kafka_driver.py").read_text() == "# fix\n"


def test_an_extra_you_never_installed_is_still_left_alone(project):
    """The fallback must not resurrect extras into tools/ that were never moved."""
    root, template = project
    (template / "extras" / "available_tools" / "postgresql" / "postgresql_tool.py").write_text("# fix\n")

    cli.main(["upgrade", "--apply"])

    assert not (root / "tools" / "postgresql").exists()
    assert (root / "extras" / "available_tools" / "postgresql" / "postgresql_tool.py").read_text() == "# fix\n"
