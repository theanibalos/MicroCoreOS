"""
`microcoreos new` — materialize a project's source into the user's directory.

The wheel ships the Kernel and nothing else that is importable. Tools, domains
and plans are copied out as YOUR source, because the install-and-swap model of
this framework is file placement (`mv extras/available_tools/postgresql tools/`,
drop a `{name}_driver.py` into `tools/event_bus/`). None of that works against
site-packages: it may be read-only, and anything written there is wiped by the
next upgrade. So: distribution as a package, materialization as your source.

The price is honest vendoring — a fix to a tool does not reach existing
projects on its own. `microcoreos upgrade` is the mitigation: this command
records the SHA-256 of everything it writes, and upgrade uses that baseline to
update only the files you never touched.
"""

import os
import shutil
import subprocess

from microcoreos.upgrade import write_manifest

# The swap catalog. Not a single "extras" entry, because the users domain is
# only PARTLY shippable: `microcoreos add auth` installs the four plugins that
# ARE auth — register, login, who-am-I, logout — while the CRUD half and the
# bus-consumer example stay in the framework's own repo. Those are what you
# write for your own entities, and shipping them would make the extra
# something to delete rather than to use.
#
# This list is the ONLY one. `hatch_build.py` derives the wheel's payload from
# it at build time, so `new` copies the same set whether it reads this repo or
# an installed `_template/`. It used to be written down twice and the two
# copies drifted the first time anyone edited one — see docs/TECH_DEBT.md.
EXTRAS_ENTRIES = [
    "extras/available_tools",
    "extras/available_domains/chaos",
    "extras/available_domains/ping",
    "extras/available_domains/scheduler",
    "extras/available_domains/users/models",
    "extras/available_domains/users/migrations",
    "extras/available_domains/users/plugins/create_user_plugin.py",
    "extras/available_domains/users/plugins/login_plugin.py",
    "extras/available_domains/users/plugins/get_me_plugin.py",
    "extras/available_domains/users/plugins/logout_plugin.py",
]

# What a project needs to boot. Nothing under domains/ that is a demo or an
# opt-in: those ride along in extras/ and `microcoreos add` moves them in.
RUNTIME_ENTRIES = [
    "tools",
    "domains/system",
    "domains/devtools",
    # Not optional: installing infrastructure here IS moving a folder
    # (`mv extras/available_tools/postgresql tools/`), so a project without
    # extras/ cannot perform the swap its own docs describe.
    *EXTRAS_ENTRIES,
    "plans",
    "dev_infra",
    # The test helpers the Plugin Authoring Guide tells every executor to
    # import — `tests.helpers.mock_db`, `.async_wait`, `.trace_chains`. They
    # were not shipped, so a fresh project's `tests/` did not exist while the
    # guide referenced it seven times and `testpaths = ["tests"]` pointed at
    # it. Executors went looking for them in whatever checkout they could
    # reach: on a measured wave, one read them straight out of the framework's
    # own repo. An instruction that names a file the project does not have is
    # an instruction to go wandering.
    "tests/helpers",
    "main.py",
    "Dockerfile",
    ".dockerignore",
    # Without it a fresh project commits .env, *.db and __pycache__ on the
    # first `git add .`. Note it does NOT ignore .microcoreos/ — that baseline
    # belongs in version control, or a teammate's clone cannot upgrade.
    ".gitignore",
    ".env.example",
]

# The AI-driven-development kit. AGENTS.md is the entry point every agent
# reads, and it points at .agent/ and docs/ — they travel together or the
# instructions dangle. `--no-ai-kit` skips the lot.
AI_KIT_ENTRIES = [
    "AGENTS.md",
    "INSTRUCTIONS_FOR_AI.md",
    ".agent",
    "docs",
]

# Never copied: build artifacts, someone else's secrets, someone else's data.
IGNORED = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".git", ".venv", "*.db", "*.db-wal", "*.db-shm",
)

PYPROJECT_TEMPLATE = """[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "microcoreos",
]

# Every plugin ships with a test — the executor contract makes it one of the
# two files — and the flow templates mark them `@pytest.mark.anyio`. Without
# these, `uv run -m pytest` on a fresh project is "No module named pytest"
# while the section below configures a runner that is not installed.
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "anyio>=4.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
"""

NEXT_STEPS = """
✅ MicroCoreOS project materialized in {target}

   Everything under tools/ and domains/ is now YOUR source — edit it, swap it,
   delete what you do not use.

   Next:
     cd {target}
     uv run microcoreos migrate      # generates AI_CONTEXT.md — do this first,
                                     # it is what an AI agent reads to know
                                     # what exists here
     uv run microcoreos              # boot

   Add auth, a database, a broker — dependency, source and .env in one step:
     uv run microcoreos add auth     # also: ping postgres redis s3 scheduler kafka rabbitmq chaos

   `uv run` is not optional: the command lives in .venv/bin, so a bare
   `microcoreos` is "command not found" until you activate the venv.
"""


def _template_root() -> str:
    """
    Where the source to copy lives.

    Installed from the wheel it is `microcoreos/_template/`. In a checkout of
    the framework itself that directory does not exist, and the repo root IS
    the template — which keeps one source of truth and makes `new` testable
    without building a wheel first.
    """
    here = os.path.dirname(os.path.abspath(__file__))

    packaged = os.path.join(here, "_template")
    if os.path.isdir(packaged):
        return packaged

    repo = os.path.dirname(here)
    if os.path.isdir(os.path.join(repo, "tools")):
        return repo

    raise FileNotFoundError(
        "This MicroCoreOS install carries no project template "
        f"(looked in {packaged}). Reinstall the package."
    )


def _copy(src: str, dst: str) -> None:
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=IGNORED, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)


def materialize(target: str, ai_kit: bool = True) -> list[str]:
    """Copy the template into `target`. Returns the entries actually copied."""
    root = _template_root()
    entries = RUNTIME_ENTRIES + (AI_KIT_ENTRIES if ai_kit else [])

    copied = []
    for entry in entries:
        src = os.path.join(root, entry)
        if not os.path.exists(src):
            # A trimmed template is not a failure: skip what is not there.
            continue
        _copy(src, os.path.join(target, entry))
        copied.append(entry)

    return copied


# `pythonpath` is the load-bearing line: without it a test cannot
# `from domains.<x>.plugins...` — pytest puts `tests/` on sys.path, not the
# project root — so every generated test fails on import, on a project that
# otherwise looks correctly set up.
PYTEST_CONFIG_BLOCK = """
# Added by `microcoreos new`. Every plugin ships with a test, and `pythonpath`
# is what lets one import the domain it tests: pytest puts tests/ on sys.path,
# not the project root.
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
"""

PYTEST_TABLE_IS_YOURS = """
   ⚠️  Your pyproject.toml already configures pytest, so it was left alone.
       Check that it carries this line — without it every generated test fails
       on import with ModuleNotFoundError: domains

         pythonpath = ["."]
"""


def _ensure_test_config(pyproject: str) -> bool:
    """Give the user's own pyproject what the generated tests need.

    The same discipline `microcoreos add` already applies to `.env`: add only
    what is missing, never rewrite what is there, and say what happened. A
    project whose tests cannot import is not a project someone forgot to
    finish — it is one that looks finished and fails on the first `pytest`.

    Appending is safe precisely BECAUSE the table is absent: a new table at the
    end of a TOML file leaves every byte above it untouched, comments included.
    When the table already exists the merge is genuinely ambiguous — two
    `pythonpath` values and no way to know which was meant — so that case says
    so rather than guessing. Python has no TOML writer in the stdlib, and
    taking a dependency in order to rewrite someone's file is a worse trade
    than one printed line.
    """
    with open(pyproject, encoding="utf-8") as f:
        existing = f.read()

    if "[tool.pytest.ini_options]" in existing:
        print(PYTEST_TABLE_IS_YOURS)
        return False

    with open(pyproject, "a", encoding="utf-8") as f:
        f.write(PYTEST_CONFIG_BLOCK)
    print("   ✓ pyproject.toml += [tool.pytest.ini_options] "
          '(testpaths, pythonpath = ["."])')
    return True


def _install_test_deps(root: str) -> bool:
    """`uv add --dev pytest anyio` — the runner the generated tests need.

    Configuring pytest in a project that does not have it installed is the
    half-step that reads as done: `testpaths` points at a suite and
    `uv run -m pytest` answers "No module named pytest".
    """
    if shutil.which("uv") is None:
        print("   ⚠ uv not found. Install them yourself: "
              "pip install pytest anyio")
        return False

    print("   $ uv add --dev pytest anyio")
    result = subprocess.run(["uv", "add", "--dev", "pytest", "anyio"], cwd=root)
    if result.returncode != 0:
        print("   ⚠ uv add failed. Run it yourself: uv add --dev pytest anyio")
        return False
    return True


def new(argv: list[str]) -> int:
    """`microcoreos new <path> [--force] [--no-ai-kit] [--no-install]`"""
    force = "--force" in argv
    ai_kit = "--no-ai-kit" not in argv
    # Same escape hatch, same spelling as `microcoreos add`: the command may
    # touch your dependencies, so there is a way to say don't.
    no_install = "--no-install" in argv
    positional = [a for a in argv if not a.startswith("-")]

    if len(positional) != 1:
        print("Usage: microcoreos new <path> [--force] [--no-ai-kit] [--no-install]")
        return 2

    target = os.path.abspath(positional[0])

    occupied = [d for d in ("tools", "domains") if os.path.isdir(os.path.join(target, d))]
    if occupied and not force:
        print(
            f"[MicroCoreOS] {target} already holds {'/'.join(occupied)}.\n"
            "              Refusing to overwrite your source. Use --force if that is what you want."
        )
        return 1

    os.makedirs(target, exist_ok=True)
    materialize(target, ai_kit=ai_kit)

    # .env is configuration, not source: never clobber one that exists.
    env, example = os.path.join(target, ".env"), os.path.join(target, ".env.example")
    if os.path.exists(example) and not os.path.exists(env):
        shutil.copy2(example, env)

    name = os.path.basename(target).replace("_", "-").lower() or "my-app"

    # Only when the directory is not already a Python project — `uv add
    # microcoreos && microcoreos new .` is a supported flow and its pyproject
    # belongs to the user.
    pyproject = os.path.join(target, "pyproject.toml")
    wrote_pyproject = False
    if not os.path.exists(pyproject):
        with open(pyproject, "w", encoding="utf-8") as f:
            f.write(PYPROJECT_TEMPLATE.format(name=name))
        wrote_pyproject = True

    # The human entry point. AGENTS.md addresses the agent; without this a
    # person opening the directory has nothing written for them. Never
    # overwrites — `uv init` already leaves a README behind.
    readme = os.path.join(target, "README.md")
    if not os.path.exists(readme):
        template = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project_readme.md")
        with open(template, encoding="utf-8") as src:
            # replace, not .format() — the template shows plugin code full of
            # dict literals, and every one of those braces would blow up.
            body = src.read().replace("{name}", name)
        with open(readme, "w", encoding="utf-8") as f:
            f.write(body)

    # The baseline `microcoreos upgrade` needs to tell your later edits from
    # a file that simply went stale.
    write_manifest(target, RUNTIME_ENTRIES + (AI_KIT_ENTRIES if ai_kit else []))

    print(NEXT_STEPS.format(target=positional[0]))

    # The pyproject we wrote already carries both; the user's carries neither,
    # and leaving them to paste it by hand is a manual step in the middle of the
    # one flow that is supposed to be a single line — `uv init && uv add
    # microcoreos && microcoreos new .` is documented as supported.
    if not wrote_pyproject:
        _ensure_test_config(pyproject)
        if not no_install:
            _install_test_deps(target)
    return 0
