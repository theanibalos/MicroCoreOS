"""
The plan pipeline commands: `status`, `plan validate`, `plan probe`, `migrate`,
`schema` — shipped by `microcoreos-dev`.

Each of these replaces a sequence an agent had to improvise, and every one of
those improvisations was observed failing in a real session: `--boot-tool db`
that never regenerates the manifest, `sqlite3` that is not installed, a
jq|curl pipeline against a server that was not running, and a plan sitting
under a filename nothing reads.

They are driven through `cli.main([...])` rather than by calling the functions
directly, which is deliberate: `microcoreos status` reaches these commands by
delegation across a package boundary now, and the spelling in every doc and
workflow is still `microcoreos <command>`. Testing the functions in isolation
would leave the seam itself uncovered.
"""

import os
import textwrap

from microcoreos import cli


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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)
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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)

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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)
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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)
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
    monkeypatch.setattr("microcoreos_dev.pipeline._open_tool",
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
    from microcoreos_dev import pipeline

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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)
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
    monkeypatch.setattr("microcoreos_dev.pipeline.Kernel", FakeKernel)

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
      tools: [event_bus, state]
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
    return project


def test_probe_records_the_calls_a_feature_actually_makes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_probe_project(tmp_path))

    cli.main(["plan", "probe"])
    out = capsys.readouterr().out

    assert "state.increment('total'" in out
    assert "event_bus.subscribe('order.placed')" in out


def test_probe_reports_tool_calls_without_gating_on_them(tmp_path, monkeypatch, capsys):
    """The plan says WHICH tools a feature may reach — `tools:` is complete by
    construction, since the kernel injects only the parameters a constructor
    names. It does not say `increment('total', namespace=...)`: that is an
    implementation, and a plan carrying it is a golden file to rewrite every
    time the code changes. So the call is printed, never failed on."""
    monkeypatch.chdir(_probe_project(tmp_path))

    exit_code = cli.main(["plan", "probe"])
    out = capsys.readouterr().out

    assert "state.increment('total'" in out
    assert exit_code == 0


def test_probe_flags_a_declared_tool_the_feature_never_uses(tmp_path, monkeypatch, capsys):
    """Plan drift the other way: the feature was specified with a capability it
    does not use, and a test written from the plan builds a stand-in for
    nothing."""
    plan = PROBE_PLAN.replace("tools: [event_bus, state]",
                              "tools: [event_bus, state, logger]")
    source = COUNTER_SOURCE.replace("def __init__(self, event_bus, state):",
                                    "def __init__(self, event_bus, state, logger):")
    monkeypatch.chdir(_probe_project(tmp_path, plan=plan, source=source))

    assert cli.main(["plan", "probe"]) == 1
    assert "`logger` is declared in `tools:` and never used" in capsys.readouterr().out


def test_probe_reports_mocks_that_do_not_fit_the_constructor(tmp_path, monkeypatch, capsys):
    """Found on the real project: three plugins took `http` and `logger` that
    their plan entry never listed, so any test written from the plan alone
    cannot construct them."""
    source = COUNTER_SOURCE.replace("def __init__(self, event_bus, state):",
                                    "def __init__(self, http, event_bus, state, logger):")
    monkeypatch.chdir(_probe_project(tmp_path, source=source))

    cli.main(["plan", "probe"])

    assert "does not fit its __init__" in capsys.readouterr().out


def test_probe_reads_a_plan_that_still_spells_it_mocks(tmp_path, monkeypatch, capsys):
    """`mocks:` is accepted forever — every plan written before the rename uses it.

    The alias on `PlanFeature.tools` is the whole mechanism, and this is the only
    thing that exercises it end to end: a plan in the old spelling has to probe.
    """
    project = _probe_project(tmp_path, plan=PROBE_PLAN.replace("tools:", "mocks:"))
    monkeypatch.chdir(project)

    exit_code = cli.main(["plan", "probe"])
    out = capsys.readouterr().out

    assert "Traceback" not in out
    assert "state.increment('total'" in out
    assert exit_code in (0, 1)


ROUTE_PLAN = """\
plan:
  domain: shop
  features:
    - plugin: ListPlugin
      file: domains/shop/plugins/list_plugin.py
      route: { method: GET, path: /orders }
      publishes:
        - event: orders.listed
          model: OrdersListedPayload
          payload: { count: int }
      tools: [http, event_bus]
      test: tests/test_list_plugin.py
"""

ROUTE_SOURCE = """\
class ListPlugin:
    def __init__(self, http, event_bus):
        self.http, self.bus = http, event_bus

    async def on_boot(self):
        self.http.add_endpoint("__PATH__", "GET", self.execute)
        await self.bus.publish("__EVENT__", {"count": 0})

    async def execute(self, data, context=None):
        return {"success": True, "data": {"count": 0}}
"""


def _route_project(tmp_path, path="/orders", event="orders.listed"):
    project = _project(tmp_path, plan=ROUTE_PLAN)
    plugins = project / "domains" / "shop" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "list_plugin.py").write_text(
        ROUTE_SOURCE.replace("__PATH__", path).replace("__EVENT__", event),
        encoding="utf-8")
    return project


def test_probe_records_sync_tool_calls_too(tmp_path, monkeypatch, capsys):
    """`http.add_endpoint(...)` is not awaited — it is a sync method on the
    real tool. Recording inside an `async def` wrapper built a coroutine nobody
    awaited, so the single most common call in the codebase was invisible."""
    monkeypatch.chdir(_route_project(tmp_path))

    cli.main(["plan", "probe"])

    assert "add_endpoint('/orders', 'GET'" in capsys.readouterr().out


def test_probe_derives_the_expected_route_from_the_plan(tmp_path, monkeypatch, capsys):
    """`route:` is not an excuse to skip http — it IS the expected call. An
    empty exemption would let a plugin register /order for a plan that says
    /orders."""
    monkeypatch.chdir(_route_project(tmp_path, path="/order"))

    assert cli.main(["plan", "probe"]) == 1
    assert "the plan declares no such http call" in capsys.readouterr().out


def test_probe_derives_expected_events_from_publishes_and_consumes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_route_project(tmp_path, event="orders.enumerated"))

    assert cli.main(["plan", "probe"]) == 1
    assert "the plan declares no such event_bus call" in capsys.readouterr().out


def test_probe_accepts_the_route_and_events_the_plan_declares(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_route_project(tmp_path))

    assert cli.main(["plan", "probe"]) == 0
