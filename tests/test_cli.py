"""
The packaged entry point (`microcoreos`, installed from the wheel).

These are the checks that the console script behaves like `uv run main.py`
even though it starts from a completely different sys.path.
"""

import io
import os
import pickle
import sys
import textwrap
import types

from microcoreos import cli


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
    (tmp_path / ".env").write_text("MICROCOREOS_ENV_PROBE=from-the-project\n", encoding="utf-8")

    cli._load_project_env(str(tmp_path))

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


# ── The plan pipeline commands ──────────────────────────────────────────────
#
# Each of these replaces a sequence an agent had to improvise, and every one of
# those improvisations was observed failing in a real session: `--boot-tool db`
# that never regenerates the manifest, `sqlite3` that is not installed, a
# jq|curl pipeline against a server that was not running, and a plan sitting
# under a filename nothing reads.


def _project(tmp_path, plan: str = "", checklist: str = ""):
    (tmp_path / "domains").mkdir()
    (tmp_path / "tools").mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    if plan:
        (plans / "active_plan.yaml").write_text(textwrap.dedent(plan), encoding="utf-8")
    if checklist:
        (plans / "active_plan.md").write_text(textwrap.dedent(checklist), encoding="utf-8")
    return tmp_path


REAL_PLAN = """\
plan:
  domain: shop
  features:
    - plugin: ListOrdersPlugin
      file: domains/shop/plugins/list_orders_plugin.py
      route: { method: GET, path: /orders }
      test: tests/test_list_orders_plugin.py
"""

TEMPLATE_PLAN = "plan:\n  template: true\n" + REAL_PLAN.split("\n", 1)[1]


def _free_port() -> str:
    """A port nothing holds. `migrate` refuses to boot onto a taken one, and
    the developer's own 5000 is frequently taken — by the very dev server this
    check exists to notice."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return str(probe.getsockname()[1])


def test_the_pipeline_commands_are_registered():
    for name in ("status", "plan", "migrate", "schema"):
        assert name in cli.COMMANDS


def test_help_mentions_every_pipeline_command(capsys):
    cli.main(["--help"])
    out = capsys.readouterr().out
    for name in ("status", "plan validate", "migrate", "schema"):
        assert name in out


def test_pipeline_commands_refuse_to_run_outside_a_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for argv in (["status"], ["migrate"], ["schema"], ["plan", "validate"]):
        assert cli.main(list(argv)) == 2, argv
    assert "No tools/ or domains/" in capsys.readouterr().out


def test_plan_without_a_subcommand_prints_usage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path))
    assert cli.main(["plan"]) == 2
    out = capsys.readouterr().out
    assert "validate" in out and "probe" in out


def test_plan_validate_rejects_the_untouched_template(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path, plan=TEMPLATE_PLAN))
    assert cli.main(["plan", "validate"]) == 1
    assert "still the shipped template" in capsys.readouterr().out


def test_plan_validate_accepts_a_real_plan_with_nothing_running(tmp_path, monkeypatch, capsys):
    """The whole point: the gate does not need the thing it gates."""
    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    assert cli.main(["plan", "validate"]) == 0
    assert "is valid" in capsys.readouterr().out


def test_plan_validate_prints_the_fix_yaml_with_the_error(tmp_path, monkeypatch, capsys):
    broken = """\
    plan:
      domain: shop
      features:
        - plugin: NotifyPlugin
          file: domains/shop/plugins/notify_plugin.py
          consumes:
            - event: order.paid
              requires: [id]
          publishes:
            - event: order.paid
              model: OrderPaidPayload
              payload: { id: int }
          test: tests/test_notify_plugin.py
    """
    monkeypatch.chdir(_project(tmp_path, plan=broken))
    assert cli.main(["plan", "validate"]) == 1
    out = capsys.readouterr().out
    assert "rule 7" in out
    assert "consumer: NotifyPlugin" in out       # the pasteable link, not a description


def test_plan_validate_takes_an_explicit_path(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, plan=TEMPLATE_PLAN)
    (project / "plans" / "draft.yaml").write_text(REAL_PLAN, encoding="utf-8")
    monkeypatch.chdir(project)
    assert cli.main(["plan", "validate", "plans/draft.yaml"]) == 0


def test_plan_validate_on_a_missing_file_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path))
    assert cli.main(["plan", "validate"]) == 2
    assert "No plan at" in capsys.readouterr().out


def test_status_flags_the_untouched_template(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(
        tmp_path, plan=TEMPLATE_PLAN, checklist="<!-- template: true -->\n- [ ] x\n"))
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "STILL THE SHIPPED TEMPLATE" in out


def test_status_reports_the_domain_and_checklist_progress(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(
        tmp_path, plan=REAL_PLAN, checklist="- [x] one\n- [x] two\n- [ ] three\n"))
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "domain `shop`" in out
    assert "2/3 tasks done" in out


def test_status_names_plans_that_nothing_will_execute(tmp_path, monkeypatch, capsys):
    """A validated plan under the wrong filename is the failure that cost the
    most: two sessions built the template's example domain while
    `plans/twitter_plan.yaml` sat there, correct and unread."""
    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "plans" / "twitter_plan.yaml").write_text("plan:\n", encoding="utf-8")
    monkeypatch.chdir(project)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "executed by nothing" in out
    assert "twitter_plan.yaml" in out


def test_status_calls_a_manifest_older_than_the_code_stale(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "AI_CONTEXT.md").write_text("# manifest\n", encoding="utf-8")
    os.utime(project / "AI_CONTEXT.md", (1_000_000, 1_000_000))
    (project / "domains" / "later.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    monkeypatch.chdir(project)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "STALE" in out and "microcoreos migrate" in out


def test_status_missing_manifest_points_at_migrate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    cli.main(["status"])
    assert "microcoreos migrate" in capsys.readouterr().out


def test_migrate_boots_once_migrates_and_shuts_down(tmp_path, monkeypatch, capsys):
    """
    `uv run main.py` regenerates the manifest but never returns: in the
    foreground it hangs the agent's session, in the background it gives no
    signal that the manifest is written and leaves the process behind. This is
    that boot with an ending — and DB_AUTO_MIGRATE is the command's definition,
    not a default it inherits.
    """
    seen = {}

    class FakeKernel:
        async def boot(self):
            seen["DB_AUTO_MIGRATE"] = os.environ.get("DB_AUTO_MIGRATE")
            (tmp_path / "AI_CONTEXT.md").write_text("# regenerated\n", encoding="utf-8")

        async def shutdown(self):
            seen["shutdown"] = True

    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)
    monkeypatch.setenv("HTTP_PORT", _free_port())

    assert cli.main(["migrate"]) == 0
    assert seen["DB_AUTO_MIGRATE"] == "true"
    assert seen["shutdown"]
    assert "AI_CONTEXT.md regenerated" in capsys.readouterr().out


def test_migrate_says_what_to_do_when_the_port_is_taken(tmp_path, monkeypatch, capsys):
    """
    A full boot binds the port, and uvicorn answers a taken one with
    `sys.exit(1)` from inside its own startup — measured: the migrate process
    dies with a traceback about sockets that says nothing about what to do.
    The check is here, in the CLI, rather than as a switch in the http tool:
    phase 0 expects nothing booted, so this is a wrong-state message, not a
    capability the framework was missing.
    """
    import socket

    class FakeKernel:
        async def boot(self):
            raise AssertionError("must not boot while the port is held")

        async def shutdown(self):
            pass

    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    monkeypatch.setenv("HTTP_PORT", str(holder.getsockname()[1]))
    try:
        assert cli.main(["migrate"]) == 2
    finally:
        holder.close()

    out = capsys.readouterr().out
    assert "already in use" in out
    assert "Stop it and run `microcoreos migrate` again" in out


def test_migrate_proceeds_when_the_port_is_free(tmp_path, monkeypatch):
    class FakeKernel:
        async def boot(self):
            (tmp_path / "AI_CONTEXT.md").write_text("# regenerated\n", encoding="utf-8")

        async def shutdown(self):
            pass

    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)
    monkeypatch.setenv("HTTP_PORT", _free_port())

    assert cli.main(["migrate"]) == 0


def test_migrate_reports_a_manifest_that_did_not_regenerate(tmp_path, monkeypatch, capsys):
    """The exact silent failure of `--boot-tool db`: migrations applied, the
    manifest untouched, and nothing said so."""
    class FakeKernel:
        async def boot(self):
            pass

        async def shutdown(self):
            pass

    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "AI_CONTEXT.md").write_text("# stale\n", encoding="utf-8")
    os.utime(project / "AI_CONTEXT.md", (1_000_000, 1_000_000))
    monkeypatch.chdir(project)
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)
    monkeypatch.setenv("HTTP_PORT", _free_port())

    assert cli.main(["migrate"]) == 1
    assert "did not regenerate" in capsys.readouterr().out


class FakeDbTool:
    """A `db` tool the CLI can find and boot on its own — no Kernel anywhere.

    Which class `db` resolves to is the entire point of the swap story, so the
    CLI cannot hardcode one; discovery answers that, and the tool answers the
    rest. Booting it is setup → describe → shutdown, and nothing else.
    """

    name = "db"
    schema: dict = {}
    calls: list = []

    async def setup(self):
        type(self).calls.append("setup")

    async def describe_schema(self):
        type(self).calls.append("describe_schema")
        return type(self).schema

    async def shutdown(self):
        type(self).calls.append("shutdown")


def _stub_db(monkeypatch, schema=None, tool=FakeDbTool):
    FakeDbTool.calls = []
    FakeDbTool.schema = schema if schema is not None else {}
    monkeypatch.setattr("microcoreos.pipeline._open_tool",
                        lambda name: tool() if tool and name == "db" else None)


def test_schema_boots_the_tool_alone_and_closes_it(tmp_path, monkeypatch):
    """A tool is self-contained: its own setup() is the whole of its startup."""
    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch)

    assert cli.main(["schema"]) == 0
    assert FakeDbTool.calls == ["setup", "describe_schema", "shutdown"]


def test_schema_closes_the_tool_even_when_reading_fails(tmp_path, monkeypatch, capsys):
    class Exploding(FakeDbTool):
        async def describe_schema(self):
            type(self).calls.append("describe_schema")
            raise RuntimeError("connection lost")

    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch, tool=Exploding)

    assert cli.main(["schema"]) == 1
    assert FakeDbTool.calls == ["setup", "describe_schema", "shutdown"]
    assert "Could not read the schema" in capsys.readouterr().out


def test_schema_prints_columns_constraints_and_relations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch, schema={
        "orders": {
            "internal": False,
            "columns": [
                {"name": "id", "type": "int", "nullable": False,
                 "default": None, "primary_key": True},
                {"name": "user_id", "type": "int", "nullable": False,
                 "default": None, "primary_key": False},
            ],
            "unique": [["user_id"]],
            "foreign_keys": [{"column": "user_id",
                              "references_table": "users",
                              "references_column": "id"}],
        }
    })

    assert cli.main(["schema"]) == 0
    out = capsys.readouterr().out
    assert "orders" in out
    assert "id: int  [PK, NOT NULL]" in out
    assert "UNIQUE(user_id)" in out
    assert "user_id \u2192 users.id" in out


def test_schema_on_an_unmigrated_project_says_nothing_is_there(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch)
    assert cli.main(["schema"]) == 0
    assert "Nothing has been migrated" in capsys.readouterr().out


def test_schema_reports_a_project_without_a_db_tool(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch, tool=None)
    assert cli.main(["schema"]) == 1
    assert "No tool named 'db'" in capsys.readouterr().out


def test_open_tool_finds_the_project_db_driver_by_name(tmp_path, monkeypatch):
    """The real discovery path: `db` is a NAME, and only discovery knows which
    class in tools/ claims it."""
    from microcoreos import pipeline

    driver = tmp_path / "tools" / "fakedb"
    driver.mkdir(parents=True)
    (driver / "fakedb_tool.py").write_text(
        "from microcoreos import BaseTool\n"
        "class FakeDbTool(BaseTool):\n"
        "    @property\n"
        "    def name(self): return 'db'\n"
        "    async def setup(self): pass\n"
        "    def get_interface_description(self): return 'Fake'\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    assert type(pipeline._open_tool("db")).__name__ == "FakeDbTool"
    assert pipeline._open_tool("nonexistent") is None


def test_the_pipeline_commands_leave_the_environment_as_they_found_it(tmp_path, monkeypatch):
    """
    A command that leaves env vars set is a command whose effect outlives it.
    The process usually exits right after, which is what hides it — until
    something else runs in the same interpreter and silently inherits
    `DB_AUTO_MIGRATE=false` from a `schema` call that only meant it for itself.
    (The suite caught exactly that: three migration tests started skipping
    their migrations.)
    """
    class FakeKernel:
        async def boot(self):
            (tmp_path / "AI_CONTEXT.md").write_text("# x\n", encoding="utf-8")

        async def shutdown(self):
            pass

    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)
    _stub_db(monkeypatch)
    monkeypatch.setenv("HTTP_PORT", _free_port())
    monkeypatch.delenv("DB_AUTO_MIGRATE", raising=False)

    cli.main(["migrate"])
    cli.main(["schema"])

    assert "DB_AUTO_MIGRATE" not in os.environ


def test_an_existing_env_value_is_restored_not_dropped(tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    _stub_db(monkeypatch)
    monkeypatch.setenv("DB_AUTO_MIGRATE", "true")

    cli.main(["schema"])

    assert os.environ["DB_AUTO_MIGRATE"] == "true"



def test_migrate_refuses_an_argument_instead_of_ignoring_it(tmp_path, monkeypatch, capsys):
    """
    `migrate` writes — to the schema and to the manifest. A flag it does not
    understand must not fall through into a real migration: `--dry-run` existed
    briefly and was removed, so a doc or a habit can still produce it.
    """
    class FakeKernel:
        async def boot(self):
            raise AssertionError("must not boot on an unknown option")

        async def shutdown(self):
            pass

    monkeypatch.chdir(_project(tmp_path, plan=REAL_PLAN))
    monkeypatch.setattr("microcoreos.kernel.Kernel", FakeKernel)

    assert cli.main(["migrate", "--dry-run"]) == 2
    assert "takes no options" in capsys.readouterr().out


def _write_baseline(project, files):
    """The `.microcoreos/` scaffold baseline, as `microcoreos new` writes it."""
    import json
    d = project / ".microcoreos"
    d.mkdir(exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps({"version": "0", "files": {f: "x" for f in files}}),
        encoding="utf-8",
    )


def test_status_names_loose_python_files_in_the_root(tmp_path, monkeypatch, capsys):
    """Observed on a real wave: an executor wrote debug_test.py, debug_test2.py
    and debug_test3.py while working out an import and left them behind. No
    plan declares them, and the next agent reads them as project source."""
    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "debug_test.py").write_text("print(1)\n", encoding="utf-8")
    (project / "debug_test2.py").write_text("print(2)\n", encoding="utf-8")
    _write_baseline(project, ["main.py"])
    monkeypatch.chdir(project)

    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out

    assert "debug_test.py, debug_test2.py" in out
    assert "no plan declares them" in out


def test_status_never_calls_a_scaffolded_file_stray(tmp_path, monkeypatch, capsys):
    """main.py is in the baseline, so it is the scaffold's, not an agent's."""
    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "main.py").write_text("# entry point\n", encoding="utf-8")
    _write_baseline(project, ["main.py"])
    monkeypatch.chdir(project)

    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out

    assert "stray" not in out


def test_status_stays_quiet_without_a_scaffold_baseline(tmp_path, monkeypatch, capsys):
    """No .microcoreos/ means this is the framework's own checkout, whose root
    legitimately holds cli.py and hatch_build.py. Reporting those was a real
    false positive before the check was anchored to the baseline."""
    project = _project(tmp_path, plan=REAL_PLAN)
    (project / "hatch_build.py").write_text("# build hook\n", encoding="utf-8")
    monkeypatch.chdir(project)

    assert cli.main(["status"]) == 0
    assert "stray" not in capsys.readouterr().out


# ── plan probe — does the CODE match the plan it was written from ────────────
#
# `validate` checks the plan's shape; this drives each feature with recording
# stand-ins and writes down every call. It exists because `mocks:` says WHICH
# tool and never WHICH resources, and those are invented per feature: on a real
# wave the plugin author wrote `increment("counter", namespace=author_id)`
# while the test author asserted `namespace="counter-{author_id}"`. Nothing
# failed until the assertion, and one agent writing both files never notices.

PROBE_PLAN = """\
plan:
  domain: shop
  features:
    - plugin: CounterPlugin
      file: domains/shop/plugins/counter_plugin.py
      consumes:
        - event: order.placed
          requires: [id, buyer_id]
      mocks: [event_bus, state]
      test: tests/test_counter_plugin.py
"""

COUNTER_SOURCE = """\
class CounterPlugin:
    def __init__(self, event_bus, state):
        self.bus, self.state = event_bus, state

    async def on_boot(self):
        await self.bus.subscribe("order.placed", self.on_order_placed)

    async def on_order_placed(self, event):
        await self.state.increment("total", namespace=event.payload["buyer_id"])
"""


def _probe_project(tmp_path, plan=PROBE_PLAN, source=COUNTER_SOURCE, touches=""):
    project = _project(tmp_path, plan=plan.replace("__TOUCHES__", touches))
    plugins = project / "domains" / "shop" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "counter_plugin.py").write_text(source, encoding="utf-8")
    # Which tools need a `touches:` is asked of the tools, never hardcoded —
    # `state` namespaces keys a feature invents, `event_bus` does not.
    for name, shape in (("state", '"namespace:key"'), ("event_bus", None)):
        d = project / "tools" / name
        d.mkdir(parents=True, exist_ok=True)
        shape_line = f"    resource_shape = {shape}\n" if shape else ""
        (d / f"{name}_tool.py").write_text(
            f"class {name.title()}Tool:\n{shape_line}"
            f"    @property\n    def name(self):\n        return \"{name}\"\n",
            encoding="utf-8")
    return project


def test_probe_records_the_calls_a_feature_actually_makes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_probe_project(tmp_path))

    cli.main(["plan", "probe"])
    out = capsys.readouterr().out

    assert "state.increment('total'" in out
    assert "event_bus.subscribe('order.placed')" in out


def test_probe_flags_a_resource_tool_the_plan_never_declared(tmp_path, monkeypatch, capsys):
    """The measured bug: `state` used, no `touches.state`, layout invented."""
    monkeypatch.chdir(_probe_project(tmp_path))

    assert cli.main(["plan", "probe"]) == 1
    assert "declares no `touches.state`" in capsys.readouterr().out


def test_probe_is_quiet_about_tools_that_declare_no_shape(tmp_path, monkeypatch, capsys):
    """`event_bus` invents no names, and says so by not declaring a
    `resource_shape`. Nothing in the pipeline lists which tools those are."""
    monkeypatch.chdir(_probe_project(tmp_path))

    cli.main(["plan", "probe"])
    out = capsys.readouterr().out

    assert "touches.event_bus" not in out


def test_probe_reports_mocks_that_do_not_fit_the_constructor(tmp_path, monkeypatch, capsys):
    """Found on the real project: three plugins took `http` and `logger` that
    their plan entry never listed, so any test written from the plan alone
    cannot construct them."""
    source = COUNTER_SOURCE.replace("def __init__(self, event_bus, state):",
                                    "def __init__(self, http, event_bus, state, logger):")
    monkeypatch.chdir(_probe_project(tmp_path, source=source))

    cli.main(["plan", "probe"])

    assert "does not fit its __init__" in capsys.readouterr().out


def test_probe_passes_when_the_plan_declares_what_the_code_touches(tmp_path, monkeypatch, capsys):
    plan = PROBE_PLAN.replace(
        "      test: tests/test_counter_plugin.py",
        "      touches:\n        state: { writes: [\"total:{buyer_id}\"] }\n"
        "      test: tests/test_counter_plugin.py")
    monkeypatch.chdir(_probe_project(tmp_path, plan=plan))

    assert cli.main(["plan", "probe"]) == 0
    assert "touches exactly what its plan entry declares" in capsys.readouterr().out
