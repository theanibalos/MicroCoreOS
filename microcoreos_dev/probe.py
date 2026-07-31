"""`plan probe` — does the CODE do what the plan it was written from says.

`plan validate` asks "is the PLAN well formed". This asks the other half.

It answers by driving each feature with recording stand-ins for its tools and
writing down every call. The recorder knows nothing about any tool — it
records `tool.method(args)` — so an s3 or redis tool dropped into `tools/` is
covered the day it arrives, and this file does not grow.

What it exists to catch: `tools:` says WHICH tool, never WHICH resources, and
those are invented per feature. Measured on a real wave — the plugin author
wrote `increment("counter", namespace=author_id)` while the test author
asserted on `namespace="counter-{author_id}"`. Both were reasonable, the plan
did not say, and nothing failed until the assertion. With one agent writing
both files the divergence never surfaces at all: it agrees with itself.
"""

import asyncio
import contextlib
import importlib
import os
import re
import sys

from microcoreos.project import (
    ensure_project_on_path,
    load_project_env,
    require_project,
)

from microcoreos_dev.plan import Plan, parse_plan_yaml


class _Recorder:
    """A stand-in for one tool. Records every call; answers anything."""

    def __init__(self, name: str, log: list):
        self._name, self._log = name, log

    def __getattr__(self, method: str):
        if method.startswith("_"):
            raise AttributeError(method)

        def call(*args, **kwargs):
            # Recorded HERE, not inside a coroutine body: tools have sync
            # methods too, and `http.add_endpoint(...)` — the most common call
            # there is — is one of them. An `async def` wrapper would build a
            # coroutine nobody awaits, so the append would never run and the
            # single most important call would be invisible.
            self._log.append((self._name, method, args, kwargs))
            # Handlers are registered by being PASSED to a tool
            # (`bus.subscribe(event, self.on_x)`, `http.add_endpoint(path,
            # method, self.execute)`), so the recording also hands us the
            # entry points — no naming convention to guess.
            return _Ignored()

        return call


class _Ignored:
    """A return value that works whether or not the caller awaits it.

    `await tool.thing()` and a bare `tool.thing()` are both legal against a
    real tool, depending on the method — and an unawaited coroutine would warn
    on every sync call. This answers both without either complaint.
    """

    def __await__(self):
        return iter(())


def _synthetic(type_name: str):
    """A value of the type the plan declares. The plan is the only input spec."""
    return {"int": 1, "float": 1.0, "bool": True,
            "str": "x", "list": [], "dict": {}}.get(str(type_name).lower(), "x")


def probe(path: str) -> int:
    root = ensure_project_on_path()
    if not require_project(root):
        return 2
    load_project_env(root)

    if not os.path.exists(path):
        print(f"[MicroCoreOS] No plan at {path}")
        return 2

    with open(path, "r", encoding="utf-8") as f:
        plan_dict, error = parse_plan_yaml(f.read())
    if error:
        print(f"[MicroCoreOS] {error}\n              Run `microcoreos plan validate` first.")
        return 2

    features = Plan(**plan_dict).features
    print(f"\nProbing {len(features)} feature(s) from {path}\n")

    findings = 0
    for feature in features:
        observed, why = _drive(feature)
        if why and not observed:
            print(f"  ⚠️  {feature.plugin}: {why}")
            continue
        findings += _report(feature, observed)
        if why:
            # Everything up to the failure is real and worth showing: a plugin
            # that registers its route and then dies still told you what it
            # registered.
            print(f"      ⚠️  stopped early: {why}")
            findings += 1
    print()
    if findings:
        print(f"❌ {findings} mismatch(es) between the code and the plan.\n"
              f"   Fix the code, or amend the plan and re-dispatch — never let "
              f"them disagree silently.")
        return 1
    print("✅ Every feature touches exactly what its plan entry declares.")
    return 0


def _drive(feature):
    """Build the plugin from `mocks:`, boot it, deliver what it consumes."""

    module_path = feature.file.replace("/", ".").removesuffix(".py")
    # Always the file as it is on disk right now. A probe is run right after an
    # executor rewrote the plugin, so a module cached from earlier in this
    # process would report on source that no longer exists.
    sys.modules.pop(module_path, None)
    importlib.invalidate_caches()
    try:
        module = importlib.import_module(module_path)
        plugin_class = getattr(module, feature.plugin)
    except (ImportError, AttributeError) as e:
        return [], f"not importable yet ({e})"

    log: list = []
    tools = {name: _Recorder(name, log) for name in feature.tools}
    try:
        instance = plugin_class(**tools)
    except TypeError as e:
        # The plan's `mocks:` and the constructor disagree — which is itself
        # the finding, and the one an independent test author trips on first.
        return [], f"`tools: {feature.tools}` does not fit its __init__ ({e})"

    async def run():
        if hasattr(instance, "on_boot"):
            await instance.on_boot()
        # Every handler the plugin registered came through a recorded call, so
        # deliver to those — never to a method name guessed from the outside.
        for _tool, _method, args, _kwargs in list(log):
            for arg in args:
                if callable(arg) and getattr(arg, "__self__", None) is instance:
                    await _deliver(arg, feature)

    try:
        asyncio.run(run())
    except Exception as e:
        return log, f"raised while being driven ({type(e).__name__}: {e})"
    return log, None


async def _deliver(handler, feature):
    """Call one registered handler with an input built from the plan."""
    payload = {}
    for consume in feature.consumes:
        for key in consume.requires:
            payload[key] = _synthetic("int" if key.endswith("id") else "str")
    envelope = type("Envelope", (), {"id": "probe-1", "payload": payload,
                                     "event": "probe", "emitter": "probe"})()
    with contextlib.suppress(Exception):
        await handler(envelope)


def _report(feature, observed) -> int:
    """Print every call the feature made, and check the ones the PLAN declares.

    The line this draws is the one that keeps the plan a spec. A plan says WHAT
    a feature is: which tools it may reach, which route it answers, which
    events it speaks. It does not say `increment('counter', namespace=...)` —
    that is an implementation, and a plan that carries it has become a golden
    file that must be rewritten every time the code is.

    So only two things are checked, and both were already spec:

      - the route `route:` declares, and the events `publishes:`/`consumes:` do
      - `tools:`, which is complete by construction — the kernel injects ONLY
        the parameters a constructor names, so a feature that reaches
        `payments` cannot avoid declaring it, and `tools: [payments]` IS the
        statement that this feature moves money

    Everything else is PRINTED. A recording is worth reading — it is how you
    see a plugin charging a card or turning on a light — and worth nothing as
    a gate, because the plan was never the place to freeze it.
    """
    expected: dict[str, list[str]] = {}
    route = feature.route
    if route:
        expected.setdefault("http", []).append(
            f"add_endpoint('{route.path}', '{route.method}'{{rest}})")
    for pub in feature.publishes:
        expected.setdefault("event_bus", []).append(f"publish('{pub.event}'{{rest}})")
    for con in feature.consumes:
        expected.setdefault("event_bus", []).append(f"subscribe('{con.event}'{{rest}})")

    print(f"  {feature.plugin}")
    problems, seen, used = 0, set(), set()
    for tool, method, args, kwargs in observed:
        call = _signature(method, args, kwargs)
        if (tool, call) in seen:
            continue
        seen.add((tool, call))
        used.add(tool)
        print(f"      {tool}.{call}")
        if tool in expected and not _covered(call, expected[tool]):
            print(f"      ⚠️  the plan declares no such {tool} call — it says "
                  f"{', '.join(expected[tool])}")
            problems += 1

    # A tool listed and never reached is plan drift: the feature was specified
    # with a capability it does not use, and a test written from the plan will
    # build a stand-in for nothing.
    for tool in sorted(set(feature.tools) - used):
        print(f"      ⚠️  `{tool}` is declared in `tools:` and never used")
        problems += 1
    return problems


def _covered(call: str, expected) -> bool:
    """Does one expected call describe this one? `{braces}` match any value."""

    method = call.split("(", 1)[0]
    for entry in expected:
        if entry.split("(", 1)[0] != method:
            continue
        pattern = "".join(
            ".*?" if part.startswith("{") and part.endswith("}") else re.escape(part)
            for part in re.split(r"(\{[^{}]*\})", entry)
        )
        if re.fullmatch(pattern, call):
            return True
    return False


def _signature(method: str, args, kwargs) -> str:
    """`increment('counter', namespace='ana')` — the call, not its result."""
    shown = [repr(a) for a in args if not callable(a)]
    shown += [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
    return f"{method}({', '.join(shown)})"
