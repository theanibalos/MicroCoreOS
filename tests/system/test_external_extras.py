"""The external-extra CLI stages code before making it discoverable."""

import json
from pathlib import Path
from types import SimpleNamespace

from microcoreos import cli, external_extras


def _project(root: Path) -> Path:
    (root / "tools").mkdir(parents=True)
    (root / "domains").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    return root


def _source(root: Path, *, dependency: str = "") -> Path:
    domain = root / "src" / "domains" / "mailer"
    (domain / "plugins").mkdir(parents=True)
    (domain / "plugins" / "send_mail_plugin.py").write_text("class SendMailPlugin: pass\n", encoding="utf-8")
    dependency_line = f'python_dependencies = ["{dependency}"]\n' if dependency else ""
    (root / external_extras.MANIFEST).write_text(
        'name = "mailer"\n'
        + dependency_line
        + '\n[environment]\nMAIL_HOST = "localhost"\n'
        + '\n[[components]]\nkind = "domain"\nsource = "src/domains/mailer"\ntarget = "mailer"\n',
        encoding="utf-8",
    )
    return root


def test_local_install_is_inactive_then_enable_copies_and_preserves_source(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source", dependency="mail-client>=1")
    monkeypatch.chdir(project)
    calls = []
    monkeypatch.setattr(external_extras.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        external_extras.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert cli.main(["extra", "install", str(source)]) == 0
    staged = project / "extras" / "installed" / "mailer"
    assert staged.is_dir()
    assert not (project / "domains" / "mailer").exists()
    assert not calls

    assert cli.main(["extra", "enable", "mailer"]) == 0
    assert (project / "domains" / "mailer" / "plugins" / "send_mail_plugin.py").is_file()
    assert staged.is_dir()
    assert (project / ".env").read_text(encoding="utf-8").find("MAIL_HOST=localhost") >= 0
    assert calls[0][0] == ["uv", "add", "mail-client>=1"]
    assert "extra enable mailer" in capsys.readouterr().out


def test_enable_keeps_existing_env_value_and_is_idempotent(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source")
    monkeypatch.chdir(project)
    (project / ".env").write_text("MAIL_HOST=mail.internal\n", encoding="utf-8")

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer"]) == 0
    first_env = (project / ".env").read_text(encoding="utf-8")
    assert "MAIL_HOST=mail.internal" in first_env
    assert "MAIL_HOST=localhost" not in first_env

    assert cli.main(["extra", "enable", "mailer"]) == 0
    assert (project / ".env").read_text(encoding="utf-8") == first_env


def test_environment_defaults_are_quoted_for_dotenv(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source")
    manifest = source / external_extras.MANIFEST
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('"localhost"', '"mail # local"'),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer", "--no-install"]) == 0
    assert dotenv_values(project / ".env")["MAIL_HOST"] == "mail # local"


def test_no_install_activates_without_invoking_uv(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source", dependency="mail-client>=1")
    monkeypatch.chdir(project)
    monkeypatch.setattr(external_extras.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        external_extras.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("uv must be skipped")),
    )

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer", "--no-install"]) == 0
    assert (project / "domains" / "mailer").is_dir()
    assert "mail-client>=1" in capsys.readouterr().out


def test_invalid_manifest_path_does_not_install(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source")
    manifest = source / external_extras.MANIFEST
    manifest.write_text(
        'name = "mailer"\n[[components]]\nkind = "domain"\n'
        'source = "../outside"\ntarget = "mailer"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    assert cli.main(["extra", "install", str(source)]) == 2
    assert not (project / "extras" / "installed").exists()
    assert "safe relative path" in capsys.readouterr().out


def test_tool_domain_and_driver_components_copy_to_their_kernel_roots(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source")
    tool = source / "src" / "tools" / "mail_transport"
    tool.mkdir(parents=True)
    (tool / "mail_tool.py").write_text("class MailTool: pass\n", encoding="utf-8")
    driver = source / "src" / "drivers" / "smtp_driver.py"
    driver.parent.mkdir(parents=True)
    driver.write_text("class SMTPDriver: pass\n", encoding="utf-8")
    manifest = source / external_extras.MANIFEST
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '\n[[components]]\nkind = "tool"\nsource = "src/tools/mail_transport"\ntarget = "mail_transport"\n'
        + '\n[[components]]\nkind = "driver"\nsource = "src/drivers/smtp_driver.py"\ntarget = "smtp_driver.py"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer", "--no-install"]) == 0
    assert (project / "tools" / "mail_transport" / "mail_tool.py").is_file()
    assert (project / "tools" / "event_bus" / "smtp_driver.py").is_file()
    assert (project / "extras" / "installed" / "mailer" / "src" / "tools" / "mail_transport" / "mail_tool.py").is_file()


def test_destination_conflict_blocks_dependency_install_and_copy(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source", dependency="mail-client>=1")
    monkeypatch.chdir(project)
    (project / "domains" / "mailer").mkdir()
    calls = []
    monkeypatch.setattr(external_extras.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(external_extras.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer"]) == 2
    assert not calls
    assert not (project / "domains" / "mailer" / "plugins").exists()
    assert "overwrite existing paths" in capsys.readouterr().out


def test_uv_failure_leaves_extra_inactive(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source", dependency="mail-client>=1")
    monkeypatch.chdir(project)
    monkeypatch.setattr(external_extras.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        external_extras.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "enable", "mailer"]) == 2
    assert not (project / "domains" / "mailer").exists()
    assert "extra was not activated" in capsys.readouterr().out


def test_git_install_pins_commit_and_redacts_url_credentials(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    monkeypatch.chdir(project)
    git_calls = []

    def fake_run(args, **kwargs):
        git_calls.append(args)
        if args[1] == "clone":
            checkout = Path(args[-1])
            _source(checkout)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(external_extras.subprocess, "run", fake_run)
    url = "https://user:secret@example.test/org/mailer.git?token=hidden"

    assert cli.main(["extra", "install", url, "--ref", "v1.2.3"]) == 0
    metadata = json.loads(
        (project / "extras" / "installed" / "mailer" / external_extras.INSTALL_META).read_text(encoding="utf-8")
    )
    assert metadata == {
        "source": "https://example.test/org/mailer.git",
        "ref": "v1.2.3",
        "commit": "abc123",
        "enabled": False,
    }
    assert ["git", "-C", str(Path(git_calls[0][-1])), "checkout", "--quiet", "--detach", "v1.2.3"] in git_calls


def test_git_clone_failure_leaves_no_installed_extra(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        external_extras.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=128, stdout="", stderr="private remote detail"),
    )

    assert cli.main(["extra", "install", "https://example.test/mail.git"]) == 2
    assert not (project / "extras" / "installed").exists()
    output = capsys.readouterr().out
    assert "Git could not fetch" in output
    assert "private remote detail" not in output


def test_invalid_git_ref_is_rejected_before_clone(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    monkeypatch.chdir(project)
    calls = []
    monkeypatch.setattr(external_extras.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert cli.main(["extra", "install", "https://example.test/mail.git", "--ref", "--help"]) == 2
    assert not calls
    assert "non-empty ref" in capsys.readouterr().out


def test_cli_help_describes_two_phase_flow(capsys):
    for argv in (["extra", "--help"], ["extra", "install", "--help"], ["extra", "enable", "--help"]):
        assert cli.main(argv) == 0
        output = capsys.readouterr().out
        assert "extra install" in output
        assert "extra enable" in output


def test_safe_source_preserves_ipv6_brackets():
    assert (
        external_extras._safe_source("https://user:secret@[::1]:8443/org/mailer.git?token=x")
        == "https://[::1]:8443/org/mailer.git"
    )


def test_extra_list_shows_empty_inactive_and_enabled_states(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path / "project")
    source = _source(tmp_path / "source")
    monkeypatch.chdir(project)

    assert cli.main(["extra", "list"]) == 0
    assert "No external extras installed." in capsys.readouterr().out

    assert cli.main(["extra", "install", str(source)]) == 0
    assert cli.main(["extra", "list"]) == 0
    out = capsys.readouterr().out
    assert "mailer" in out
    assert "[inactive]" in out

    assert cli.main(["extra", "enable", "mailer", "--no-install"]) == 0
    assert cli.main(["extra", "list"]) == 0
    out = capsys.readouterr().out
    assert "mailer" in out
    assert "[enabled]" in out

    assert cli.main(["extra", "list", "--help"]) == 0
    assert "extra list" in capsys.readouterr().out
