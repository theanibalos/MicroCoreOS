"""
`microcoreos new` — the onboarding path that replaces "clone the repo".

What matters here is not that files land somewhere: it is that the result is a
directory the user OWNS (editable tools, no framework code copied in) and that
the command never destroys work that was already there.
"""

import os
import tomllib
from pathlib import Path

from microcoreos import cli, scaffold


def test_template_root_is_the_repo_in_a_checkout():
    """No _template/ in a checkout of the framework: the repo root IS it."""
    root = scaffold._template_root()
    assert os.path.isdir(os.path.join(root, "tools"))
    assert os.path.isdir(os.path.join(root, "domains", "system"))


def test_new_materializes_a_bootable_project(tmp_path):
    target = tmp_path / "demo"
    assert cli.main(["new", str(target)]) == 0

    # The infrastructure the user now owns.
    assert (target / "tools" / "sqlite" / "sqlite_tool.py").is_file()
    assert (target / "domains" / "system" / "plugins").is_dir()
    assert (target / "domains" / "devtools" / "plugins").is_dir()
    assert (target / "main.py").is_file()
    assert (target / "plans").is_dir()

    # The framework itself is NOT copied — it comes from the wheel.
    assert not (target / "microcoreos").exists()

    # The swap catalog: `mv extras/available_tools/postgresql tools/` is how
    # infrastructure is installed here, so the catalog has to be there.
    assert (target / "extras" / "available_tools" / "postgresql").is_dir()
    assert (target / "extras" / "available_domains").is_dir()

    # Auth is an extra: a fresh project has no users table, no JWT and no
    # AUTH_SECRET_KEY requirement until someone asks for it.
    assert not (target / "tools" / "auth").exists()
    assert not (target / "domains" / "users").exists()

    # It is available, though, and `add auth` is what moves it into place.
    plugins = target / "extras" / "available_domains" / "users" / "plugins"
    assert (target / "extras" / "available_tools" / "auth" / "auth_tool.py").is_file()
    assert (plugins / "create_user_plugin.py").is_file()
    assert (plugins / "login_plugin.py").is_file()
    assert (plugins / "get_me_plugin.py").is_file()
    assert (plugins / "logout_plugin.py").is_file()
    assert (
        target / "extras" / "available_domains" / "users" / "migrations" / "001_create_users.sql"
    ).is_file()

    # The CRUD around it stays behind — you write that for your own entities.
    assert not (plugins / "delete_user_plugin.py").exists()
    assert not (plugins / "get_users_plugin.py").exists()
    assert not (plugins / "welcome_service_plugin.py").exists()

    # And the pure demo domain never ships.
    assert not (target / "domains" / "ping").exists()


def test_new_writes_env_and_pyproject_when_absent(tmp_path):
    target = tmp_path / "demo"
    cli.main(["new", str(target)])

    assert (target / ".env").is_file()
    assert "microcoreos" in (target / "pyproject.toml").read_text(encoding="utf-8")


def test_new_never_clobbers_an_existing_env_or_pyproject(tmp_path):
    """`uv add microcoreos && microcoreos new .` is a supported flow: that
    pyproject and that .env belong to the user."""
    target = tmp_path / "demo"
    target.mkdir()
    (target / ".env").write_text("AUTH_SECRET_KEY=mine\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "mine"\n', encoding="utf-8")

    assert cli.main(["new", str(target)]) == 0
    assert (target / ".env").read_text(encoding="utf-8") == "AUTH_SECRET_KEY=mine\n"
    assert (target / "pyproject.toml").read_text(encoding="utf-8") == '[project]\nname = "mine"\n'


def test_new_refuses_to_overwrite_existing_source(tmp_path, capsys):
    target = tmp_path / "demo"
    (target / "tools").mkdir(parents=True)

    assert cli.main(["new", str(target)]) == 1
    assert "Refusing to overwrite" in capsys.readouterr().out

    assert cli.main(["new", str(target), "--force"]) == 0


def test_no_ai_kit_skips_the_agent_instructions(tmp_path):
    target = tmp_path / "demo"
    cli.main(["new", str(target), "--no-ai-kit"])

    assert (target / "tools").is_dir()
    assert not (target / "AGENTS.md").exists()
    assert not (target / ".agent").exists()


def test_ai_kit_travels_whole(tmp_path):
    """AGENTS.md points at .agent/ and docs/ — copying it alone leaves the
    agent reading instructions that dangle."""
    target = tmp_path / "demo"
    cli.main(["new", str(target)])

    assert (target / "AGENTS.md").is_file()
    assert (target / ".agent" / "workflows").is_dir()
    assert (target / "docs").is_dir()


def test_nothing_compiled_or_private_is_copied(tmp_path):
    target = tmp_path / "demo"
    cli.main(["new", str(target)])

    assert not list(target.rglob("__pycache__"))
    assert not list(target.rglob("*.pyc"))
    assert not list(target.rglob("*.db"))


def test_new_without_a_path_reports_usage(capsys):
    assert cli.main(["new"]) == 2
    assert "Usage: microcoreos new" in capsys.readouterr().out


def test_new_writes_a_human_readme_named_after_the_project(tmp_path):
    """AGENTS.md addresses the agent; a person opening the folder needs one too."""
    target = tmp_path / "my_shop"
    cli.main(["new", str(target)])

    readme = (target / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# my-shop")
    # The plugin example is full of dict literals — proof the template is not
    # run through .format().
    assert '{"success": True}' in readme
    assert "microcoreos dev" in readme


def test_new_never_clobbers_an_existing_readme(tmp_path):
    """`uv init` leaves one behind, and it is the user's."""
    target = tmp_path / "demo"
    target.mkdir()
    (target / "README.md").write_text("# mine\n", encoding="utf-8")

    cli.main(["new", str(target)])
    assert (target / "README.md").read_text(encoding="utf-8") == "# mine\n"


def test_the_wheel_payload_is_derived_not_retyped():
    """
    `new` copies from the repo root in a checkout and from `_template/` when
    installed, and what to copy used to be written down twice: RUNTIME_ENTRIES
    here, a `force-include` table in pyproject.toml there. They drifted the
    first time one was edited — moving auth into an extra shipped 4 plugins
    packaged and copied 9 from a checkout, invisibly, because you only see it
    by building a wheel.

    `hatch_build.py` derives the table from RUNTIME_ENTRIES now. This asserts
    nobody hand-writes the second copy again.
    """
    root = Path(__file__).resolve().parent.parent
    with open(root / "pyproject.toml", "rb") as f:
        wheel_cfg = tomllib.load(f)["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "force-include" not in wheel_cfg, (
        "pyproject.toml hand-lists the template payload again. That table is "
        "generated by hatch_build.py from scaffold.RUNTIME_ENTRIES — a second "
        "copy is exactly what shipped a wrong wheel once."
    )
    assert wheel_cfg["hooks"]["custom"]["path"] == "hatch_build.py"


def test_every_entry_the_wheel_will_carry_exists():
    """
    The build hook maps entry → `_template/<entry>`, and `materialize` skips a
    source that is not there. So a typo in RUNTIME_ENTRIES does not fail: it
    silently ships one file fewer, in both directions at once now that the two
    lists are one.
    """
    root = Path(__file__).resolve().parent.parent
    missing = [
        e for e in scaffold.RUNTIME_ENTRIES + scaffold.AI_KIT_ENTRIES
        if not (root / e).exists()
    ]
    assert not missing, f"entries naming nothing on disk: {missing}"
