"""
`microcoreos add <extra>` — install an extra completely, in one command.

Activating an extra by hand is three separate acts, and skipping any one of
them fails in a different place:

    uv add 'microcoreos[postgres]'                  the library, or ImportError at boot
    mv extras/available_tools/postgresql tools/     the source, or nothing happens at all
    edit .env                                       the settings, or it connects nowhere

This module holds what each extra IS, so the command can do all three. The
catalog is the single place that knows an extra's dependency, its folders and
its environment — the READMEs and docs describe it, this executes it.
"""

import os
import shutil
import subprocess

from microcoreos.upgrade import record_move


class Extra:
    def __init__(self, dependency=None, tool=None, domain=None, driver=None, env=(), note=None):
        self.dependency = dependency  # the pyproject extra, e.g. "postgres"
        self.tool = tool              # folder under extras/available_tools/
        self.domain = domain          # folder under extras/available_domains/
        self.driver = driver          # event-bus driver: file goes into tools/event_bus/
        self.env = env                # (name, value, comment) appended to .env
        self.note = note              # printed after install


CATALOG = {
    # Unlike every other entry here, auth needs no external service — it is an
    # extra because a framework should not force a users table, a roles model
    # and a JWT flavour on a project that wants none, nor make AUTH_SECRET_KEY
    # a boot requirement for one that never logs anyone in. `http_server_tool`
    # takes auth_validator as an optional callback and never imports auth, so
    # nothing in a default project notices its absence.
    "auth": Extra(
        dependency="auth",
        tool="auth",
        domain="users",
        env=[
            # 32 characters minimum — AuthTool refuses to boot below that, so a
            # shorter placeholder would hand the user a project that dies on
            # the first run. See test_catalog.py.
            ("AUTH_SECRET_KEY", "super-secret-key-change-me-in-production", "CHANGE THIS — 32 chars minimum"),
            ("AUTH_TOKEN_EXPIRE_MINUTES", "60", "JWT expiry in minutes"),
        ],
        note="The domain adds register, login, who-am-I and logout. The CRUD "
             "for your own entities is yours to write.",
    ),
    # The hello-world. AGENTS.md sends every agent here for the shape of a
    # plugin with no database and no dependencies, and before this it pointed
    # at a path that existed in the framework's checkout and in no project ever
    # scaffolded from it. Installable rather than materialized: a live /ping in
    # production is somebody's incident, and this is a domain you read once and
    # delete.
    "ping": Extra(
        domain="ping",
        note="A single GET /ping. Read it for the shape, then delete domains/ping.",
    ),
    "postgres": Extra(
        dependency="postgres",
        tool="postgresql",
        env=[
            ("PG_HOST", "localhost", None),
            ("PG_PORT", "5432", None),
            ("PG_USER", "postgres", None),
            ("PG_PASSWORD", "postgres", None),
            ("PG_DATABASE", "microcoreos", None),
        ],
        note="Remove tools/sqlite/ (or keep both — the LAST one to register wins the 'db' key).",
    ),
    "redis": Extra(
        dependency="redis",
        tool="redis_state",
        env=[
            ("REDIS_HOST", "localhost", None),
            ("REDIS_PORT", "6379", None),
            ("REDIS_DB", "0", None),
            ("REDIS_PASSWORD", "", "leave empty for no auth"),
        ],
        note="Swaps the in-memory state tool. For the Redis Streams EVENT BUS instead, "
             "set EVENT_BUS_DRIVER=redis_streams — that driver already ships in tools/event_bus/.",
    ),
    "s3": Extra(
        dependency="s3",
        tool="s3",
        env=[
            ("AWS_ACCESS_KEY_ID", "your-access-key", None),
            ("AWS_SECRET_ACCESS_KEY", "your-secret-key", None),
            ("AWS_DEFAULT_REGION", "us-east-1", None),
            ("AWS_S3_ENDPOINT_URL", "http://localhost:9000", "MinIO in dev; drop for real S3"),
            ("AWS_S3_DEFAULT_BUCKET", "microcoreos-bucket", None),
        ],
    ),
    "scheduler": Extra(
        dependency="scheduler",
        tool="scheduler",
        domain="scheduler",
        env=[
            ("SCHEDULER_ENABLED", "true", "false on worker replicas — jobs fire in ONE beat replica"),
        ],
        note="The domain adds durable one-shots: the scheduler.one_shot.* bus API.",
    ),
    "kafka": Extra(
        dependency="kafka",
        driver="kafka",
        env=[
            ("EVENT_BUS_DRIVER", "kafka", None),
            ("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092", None),
        ],
    ),
    "rabbitmq": Extra(
        dependency="rabbitmq",
        driver="rabbitmq",
        env=[
            ("EVENT_BUS_DRIVER", "rabbitmq", None),
            ("RABBITMQ_HOST", "localhost", None),
            ("RABBITMQ_PORT", "5672", None),
            ("RABBITMQ_USER", "guest", None),
            ("RABBITMQ_PASSWORD", "guest", None),
        ],
    ),
    "chaos": Extra(
        tool="chaos",
        domain="chaos",
        env=[("CHAOS_ENABLED", "true", "NEVER enable in production")],
    ),
}


def _move(src: str, dst: str, root: str) -> bool:
    """Move a folder into place. False if it was not there to move."""
    if not os.path.isdir(src):
        return False
    if os.path.exists(dst):
        print(f"   ⚠ {os.path.relpath(dst, root)} already exists — left untouched.")
        return False
    shutil.move(src, dst)
    src_rel = os.path.relpath(src, root).replace(os.sep, "/")
    dst_rel = os.path.relpath(dst, root).replace(os.sep, "/")
    # `microcoreos upgrade` keys its baseline by UPSTREAM path; without this it
    # would look for the extra where it used to be and never offer its fixes.
    record_move(root, src_rel, dst_rel)
    print(f"   ✓ {src_rel} → {dst_rel}")
    return True


def _install_dependency(extra: str, root: str) -> bool:
    """
    `uv add 'microcoreos[<extra>]'`.

    Only when uv is present AND this is a Python project — the command edits
    the user's pyproject and lockfile, so it never runs blind.
    """
    spec = f"microcoreos[{extra}]"

    if not os.path.exists(os.path.join(root, "pyproject.toml")):
        print(f"   ⚠ No pyproject.toml here. Install it yourself: uv add '{spec}'")
        return False

    if shutil.which("uv") is None:
        print(f"   ⚠ uv not found. Install it yourself: pip install '{spec}'")
        return False

    print(f"   $ uv add '{spec}'")
    result = subprocess.run(["uv", "add", spec], cwd=root)
    if result.returncode != 0:
        print(f"   ⚠ uv add failed. Run it yourself: uv add '{spec}'")
        return False
    return True


ENV_BOX_WIDTH = 76


def _env_section_header(title: str, source: str) -> list:
    """
    One boxed heading per tool, so .env stays readable as extras accumulate.
    .env.example uses this same function; keep the three lines equal in width
    or the boxes stop lining up.
    """
    left = f"  {title}"
    pad = ENV_BOX_WIDTH - len(left) - len(source) - 2
    return [
        f"# ╭{'─' * ENV_BOX_WIDTH}╮",
        f"# │{left}{' ' * max(pad, 1)}{source}  │",
        f"# ╰{'─' * ENV_BOX_WIDTH}╯",
    ]


def _env_state(existing: str, var: str) -> str:
    """Whether var is absent, set, or present but commented out."""
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{var}="):
            return "set"
        if stripped.startswith("#") and stripped.lstrip("#").strip().startswith(f"{var}="):
            return "commented"
    return "absent"


def _append_env(root: str, name: str, entries) -> None:
    """
    Append the extra's settings to .env, once.

    Anything already defined there is the user's decision and is left alone —
    re-running `add` must never rewrite a password someone typed.

    A commented-out setting counts as already there. It is not appended again:
    python-dotenv gives precedence to the LAST occurrence, so the duplicate
    would override the line above it and editing that line would do nothing.
    Which of the two the user meant is not knowable here — commenting a
    variable reads equally as "I want the default" and as "I will fill this in
    later" — so the choice is reported rather than made.
    """
    if not entries:
        return

    path = os.path.join(root, ".env")
    existing = ""
    if os.path.exists(path):
        existing = open(path, encoding="utf-8").read()

    states = {e[0]: _env_state(existing, e[0]) for e in entries}
    missing = [e for e in entries if states[e[0]] == "absent"]
    commented = [v for v, s in states.items() if s == "commented"]

    for var in commented:
        print(f"   ! .env has {var} commented out — uncomment it or delete the line.")

    if not missing:
        print("   ✓ .env already has these settings — unchanged.")
        return

    block = [""] + _env_section_header(name.upper(), f"microcoreos add {name}") + [""]
    for var, value, comment in missing:
        block.append(f"{var}={value}" + (f"   # {comment}" if comment else ""))

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(block) + "\n")
    print(f"   ✓ .env += {', '.join(v for v, _, _ in missing)}")


def add(argv: list[str]) -> int:
    """`microcoreos add <extra> [--no-install]`"""
    no_install = "--no-install" in argv
    positional = [a for a in argv if not a.startswith("-")]

    if len(positional) != 1 or positional[0] not in CATALOG:
        known = ", ".join(sorted(CATALOG))
        print(f"Usage: microcoreos add <extra> [--no-install]\n\nAvailable: {known}")
        return 2

    name = positional[0]
    extra = CATALOG[name]
    root = os.getcwd()

    if not any(os.path.isdir(os.path.join(root, d)) for d in ("tools", "domains")):
        print(
            f"[MicroCoreOS] No tools/ or domains/ directory in {root}.\n"
            "              Run this from the root of a MicroCoreOS project."
        )
        return 2

    print(f"\n📦 Installing extra '{name}'\n")

    if extra.dependency and not no_install:
        _install_dependency(extra.dependency, root)
    elif extra.dependency:
        print(f"   (skipped: uv add 'microcoreos[{extra.dependency}]')")

    # The tool first: a plugin cannot exist without the tool it asks for, so
    # installing the domain first would leave a boot that aborts it.
    if extra.tool:
        _move(
            os.path.join(root, "extras", "available_tools", extra.tool),
            os.path.join(root, "tools", extra.tool),
            root,
        )

    if extra.driver:
        src = os.path.join(root, "extras", "available_tools", extra.driver, f"{extra.driver}_driver.py")
        dst = os.path.join(root, "tools", "event_bus", f"{extra.driver}_driver.py")
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            record_move(
                root,
                f"extras/available_tools/{extra.driver}/{extra.driver}_driver.py",
                f"tools/event_bus/{extra.driver}_driver.py",
            )
            print(f"   ✓ {extra.driver}_driver.py → tools/event_bus/")

    if extra.domain:
        _move(
            os.path.join(root, "extras", "available_domains", extra.domain),
            os.path.join(root, "domains", extra.domain),
            root,
        )

    _append_env(root, name, extra.env)

    if extra.note:
        print(f"\n   ℹ {extra.note}")

    print("\n   Restart to pick it up: microcoreos\n")
    return 0
