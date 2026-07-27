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


def test_every_manifest_path_is_slash_separated(project):
    """
    The manifest is a published format read on every platform, so its keys are
    POSIX-style everywhere — `os.sep` must never reach the file. On Linux this
    passes for free; it is the Windows job in CI that gives it teeth.
    """
    root, _ = project
    assert cli.main(["add", "kafka", "--no-install"]) == 0
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))
    assert cli.main(["upgrade"]) == 0                       # records the rename

    manifest = upgrade.read_manifest(str(root))
    paths = (list(manifest["files"])
             + list(manifest.get("moved", {}))
             + list(manifest.get("moved", {}).values()))
    assert paths
    assert not [p for p in paths if "\\" in p]


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


# ─── Withdrawn upstream ───────────────────────────────────────────────
#
# The symmetric half of "update only what you never touched": a file the
# framework drops is the framework's to withdraw — unless you edited it,
# in which case it is yours, exactly like every other case here.


def test_a_file_withdrawn_upstream_is_deleted(project):
    root, template = project
    os.remove(template / "tools" / "state" / "state_tool.py")

    assert cli.main(["upgrade", "--apply"]) == 0

    assert not (root / "tools" / "state" / "state_tool.py").exists()
    # And it leaves the baseline, or every later run re-reports it.
    baseline = upgrade.read_manifest(str(root))["files"]
    assert "tools/state/state_tool.py" not in baseline


def test_a_withdrawn_file_you_edited_is_kept(project, capsys):
    root, template = project
    os.remove(template / "tools" / "state" / "state_tool.py")
    (root / "tools" / "state" / "state_tool.py").write_text("# my patch\n")

    assert cli.main(["upgrade", "--apply"]) == 0

    assert (root / "tools" / "state" / "state_tool.py").read_text() == "# my patch\n"
    assert "Removed upstream but edited by you" in capsys.readouterr().out


def test_a_withdrawn_file_you_edited_is_released_not_nagged_about(project, capsys):
    """
    Upstream does not ship it and you changed it: there is nothing left for the
    baseline to compare. Kept in it, the file would be re-reported on every run
    for ever — which is exactly how a warning stops being read.
    """
    root, template = project
    os.remove(template / "tools" / "state" / "state_tool.py")
    (root / "tools" / "state" / "state_tool.py").write_text("# my patch\n")

    cli.main(["upgrade", "--apply"])
    capsys.readouterr()

    assert cli.main(["upgrade"]) == 0
    out = capsys.readouterr().out
    assert "Removed upstream" not in out
    assert "Everything is current" in out
    assert (root / "tools" / "state" / "state_tool.py").read_text() == "# my patch\n"


def test_a_broken_template_releases_nothing_either(project, capsys):
    """The guard must cover the release too, or a partial wheel untracks the lot."""
    root, template = project
    (root / "tools" / "state" / "state_tool.py").write_text("# my patch\n")
    shutil.rmtree(template / "tools")

    assert cli.main(["upgrade", "--apply"]) == 0

    assert "broken template" in capsys.readouterr().out
    baseline = upgrade.read_manifest(str(root))["files"]
    assert "tools/state/state_tool.py" in baseline


def test_a_dry_run_deletes_nothing(project):
    root, template = project
    os.remove(template / "tools" / "state" / "state_tool.py")

    assert cli.main(["upgrade"]) == 0
    assert (root / "tools" / "state" / "state_tool.py").exists()


def test_withdrawing_a_whole_tool_takes_its_folder_with_it(project):
    """An empty tools/<name>/ left behind is the mess this is meant to clean."""
    root, template = project
    shutil.rmtree(template / "tools" / "state")

    assert cli.main(["upgrade", "--apply"]) == 0
    assert not (root / "tools" / "state").exists()


def test_a_wholesale_disappearance_is_read_as_a_broken_template(project, capsys):
    """
    A partial wheel looks exactly like "upstream deleted everything". Acting on
    that reading would empty the user's project.
    """
    root, template = project
    shutil.rmtree(template / "tools")
    shutil.rmtree(template / "domains")

    assert cli.main(["upgrade", "--apply"]) == 0

    assert (root / "tools" / "sqlite" / "sqlite_tool.py").exists()
    assert "broken template" in capsys.readouterr().out


# ─── Renamed where the convention cannot follow ───────────────────────


def test_a_folder_renamed_off_convention_is_found_by_content(project):
    """
    `mv extras/available_tools/postgresql tools/my-db` is not one of the three
    documented destinations, so name-based tracking loses it and upgrade
    reports "everything is current" while fixes never arrive. The baseline
    digest still identifies the file wherever it sits.
    """
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))

    (template / "extras" / "available_tools" / "postgresql" / "postgresql_tool.py").write_text("# fix\n")

    assert cli.main(["upgrade", "--apply"]) == 0
    assert (root / "tools" / "my-db" / "postgresql_tool.py").read_text() == "# fix\n"
    # Written where it lives — not recreated back in extras/.
    assert not (root / "extras" / "available_tools" / "postgresql").exists()


def test_a_rename_is_recorded_so_a_later_edit_cannot_lose_it(project):
    """
    Content is the only evidence, and editing the file destroys it. So the
    move is written to the manifest the moment it is found, and from then on
    the file is tracked by name like any other.
    """
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))

    assert cli.main(["upgrade"]) == 0                       # a dry run finds it
    moved = upgrade.read_manifest(str(root)).get("moved", {})
    assert moved.get("extras/available_tools/postgresql") == "tools/my-db"

    # Now edit it — the content evidence is gone, the record is not.
    (root / "tools" / "my-db" / "postgresql_tool.py").write_text("# my patch\n")
    (template / "extras" / "available_tools" / "postgresql" / "postgresql_tool.py").write_text("# fix\n")

    report = upgrade.classify(str(root), str(template),
                              upgrade.read_manifest(str(root))["files"],
                              upgrade.read_manifest(str(root)).get("moved", {}))
    assert "extras/available_tools/postgresql/postgresql_tool.py" in report["conflict"]


def test_a_renamed_folder_also_receives_files_added_upstream_later(project):
    """
    Why the FOLDER move is recorded and not the file move: a per-file record
    only tracks what existed on the day of the rename.
    """
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))

    assert cli.main(["upgrade"]) == 0                       # records the rename
    (template / "extras" / "available_tools" / "postgresql" / "pool.py").write_text("# new\n")

    assert cli.main(["upgrade", "--apply"]) == 0
    assert (root / "tools" / "my-db" / "pool.py").read_text() == "# new\n"
    assert not (root / "extras" / "available_tools" / "postgresql").exists()


def test_one_file_moved_is_not_read_as_the_folder_moving(project):
    root, template = project
    src = root / "extras" / "available_tools" / "postgresql"
    shutil.move(str(src / "postgresql_tool.py"), str(root / "tools" / "my-db.py"))

    assert cli.main(["upgrade"]) == 0

    moved = upgrade.read_manifest(str(root)).get("moved", {})
    assert moved.get("extras/available_tools/postgresql/postgresql_tool.py") == "tools/my-db.py"
    assert "extras/available_tools/postgresql" not in moved


def test_an_unwritable_manifest_degrades_the_report_instead_of_crashing(project, monkeypatch):
    """
    A report-only `upgrade` now writes what it discovers, so it must survive a
    project it cannot write to — with a correct report, not a traceback.
    """
    root, _ = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))

    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(upgrade.json, "dump", boom)
    assert cli.main(["upgrade"]) == 0


def test_content_shared_by_two_files_identifies_neither(project):
    """A digest that names more than one candidate is not evidence of anything."""
    root, template = project
    shutil.move(str(root / "extras" / "available_tools" / "postgresql"),
                str(root / "tools" / "my-db"))
    (root / "tools" / "my-db-backup").mkdir()
    shutil.copy2(root / "tools" / "my-db" / "postgresql_tool.py",
                 root / "tools" / "my-db-backup" / "postgresql_tool.py")

    assert cli.main(["upgrade"]) == 0

    moved = upgrade.read_manifest(str(root)).get("moved", {})
    assert "extras/available_tools/postgresql" not in moved
    assert "extras/available_tools/postgresql/postgresql_tool.py" not in moved


def test_a_file_you_deleted_is_not_mistaken_for_a_rename(project):
    """Deleting a tool is a supported act: nothing on disk holds its content."""
    root, _ = project
    os.remove(root / "tools" / "state" / "state_tool.py")

    assert cli.main(["upgrade", "--apply"]) == 0

    assert not (root / "tools" / "state" / "state_tool.py").exists()
    moved = upgrade.read_manifest(str(root)).get("moved", {})
    assert "tools/state/state_tool.py" not in moved
