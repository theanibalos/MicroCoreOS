# Roadmap — completed decisions and implementation history

> Historical record, not current implementation instructions. Dates, old paths,
> intermediate designs and measurements below describe their original sessions.
> Current work and remaining subscopes live in [ROADMAP.md](ROADMAP.md).
> “Completed” includes deliberate decisions not to build a feature.

## ✅ Decision Log (completed)

### Foundations & DX

**Issue 39 — ✅ Core as an installable package (`uv add microcoreos`) — scoped 2026-07-27, built 2026-07-27, PUBLISHED 2026-07-28**

> **Status:** shipped. [`microcoreos 0.1.0` is on PyPI](https://pypi.org/project/microcoreos/),
> published by tag through `.github/workflows/release.yml` — OIDC trusted
> publishing, no API token anywhere. Rehearsed on TestPyPI first, which is what
> it is for: the real run then failed once on a network timeout to
> `upload.pypi.org` and a re-run fixed it, with nothing uploaded and the version
> number intact.
>
> Verified from a clean venv against the real index, not a path dependency:
> `uv pip install 'microcoreos[auth]'` resolves, `microcoreos add postgres`
> runs its own `uv add` without `--no-install` and lands asyncpg, and the
> resulting project boots with 11 tools and 22 plugins.
>
> Known gaps and their cost are recorded in [docs/internal/TECH_DEBT.md](docs/internal/TECH_DEBT.md),
> where every item is now closed or a standing note.
>
> **The free-breaking window is closed.** Three things are compatibility
> surface as of 0.1.0: the five names re-exported from
> `microcoreos/__init__.py`, the `[project.optional-dependencies]` extra names
> as published (`auth`, `kafka`, `postgres`, `rabbitmq`, `redis`, `s3`,
> `scheduler`, `all`), and the `.microcoreos/manifest.json` format — readers
> already tolerate missing keys (`.get("moved", {})`), and must keep doing so.
>
> Built past the original checklist: `microcoreos add` (Issue 39 assumed manual
> `mv`), `microcoreos upgrade` + the `.microcoreos/manifest.json` baseline
> (was future work), a generated project README and `docs/CLI.md`.
>
> **Auth ended up an extra, not a starter.** The original plan materialized
> `create_user`/`login`/`get_me` so `tools/auth` would not be a tool you cannot
> use. Decided the other way on 2026-07-28: a framework should not impose a
> users table, a roles model and a JWT flavour on a project that wants none,
> nor make `AUTH_SECRET_KEY` a boot requirement for one that never logs anyone
> in. `microcoreos add auth` installs the tool plus register, login, who-am-I
> and **logout** — which had never materialized before, so every scaffolded
> project shipped a login with no way out. `bcrypt` and `pyjwt` left the base
> install with it; nothing else imported them. `ping` went the same way, since
> AGENTS.md pointed every agent at a path no scaffolded project ever had.

Only `core/` ships in the wheel (570 lines: Kernel, Container, Registry, the two
base classes, the identity ContextVars). Everything else — `tools/` (4.9k),
`domains/system` + `devtools` (2.5k), `plans/`, `dev_infra/` — is **materialized
as the user's own source** by a `microcoreos new` scaffolder.

**Why not ship the tools too.** The whole install and swap model of this
codebase is file placement: `mv extras/available_tools/postgresql tools/`
(README, `docs/ELASTIC_DEPLOYMENT.md`), and drivers install by dropping
`{name}_driver.py` into `tools/event_bus/`. None of that works against
`site-packages`: it may be read-only, and anything copied there is wiped by the
next `pip install --upgrade`. Tools in the wheel = tools the user cannot touch,
which contradicts the premise that you own your infrastructure. Distribution as
a package, materialization as your source (the shadcn/ui model) keeps both.

The cost is honest vendoring: an event-bus fix does not reach existing projects
on its own. A `microcoreos upgrade` showing a diff is the mitigation, later.

**What the split actually costs, in order:**

1. **The `core` name — rename is mandatory, and the reason is not PyPI.** A
   wheel may ship any top-level name regardless of its project name (`pillow` →
   `PIL`, `scikit-learn` → `sklearn`), so keeping `core` is technically possible.
   It is still wrong: a MicroCoreOS project is a directory holding `tools/`,
   `domains/`, `plans/`, and sooner or later the user adds a `core/` of their own
   for shared logic. Their directory WINS — the project root is `sys.path[0]` —
   and the framework vanishes. Every plugin then fails with
   `cannot import name 'base_plugin' from 'core'`, pointing at a folder the user
   created for entirely reasonable reasons. Verified by construction. Note the
   problem is exclusive to what ships in the wheel: `tools/` and `domains/` stay
   in the project under this model, so nothing installed can shadow them.

   **Flatten the public API while renaming.** Plugins touch exactly five names —
   `BasePlugin` (37 uses), `BaseTool` (21), `ToolUnavailableError` (10), the two
   context vars (7) — 75 of the 83 `core.*` imports. Re-export those from
   `microcoreos/__init__.py` so a plugin writes `from microcoreos import
   BasePlugin`, and keep `Kernel`/`Container`/`Registry` in submodules (12 sites,
   only `main.py` and tests). This is the `__init__.py`-as-public-address rule
   learned the hard way in Issue 41: `from core.base_plugin import BasePlugin`
   welds the FILE LAYOUT into every plugin the LLM has ever generated, so core
   cannot be reorganized without a breaking change. One short stable line also
   costs the LLM less in every file it writes.

   **Effort is concentrated, not spread.** The 83 imports and 8 docs are a `sed`
   over ~6 patterns, with the suite as an instant check. The risk lives in 10
   files where `core.*` appears inside strings and regexes that must keep
   matching generated code — the templates in `context_tool.py` and the nine
   devtools linters. A wrong pattern there does not fail; it silently stops
   detecting. Those go by hand, each with a test proving the linter still finds
   the violation it is supposed to find.

   **Do it before publishing.** Renaming is breaking for anyone holding generated
   plugins. With nothing released yet, now is the cheapest this will ever be.
2. **`[build-system]`** — absent today, so no wheel can be built at all. Plus
   `[project.scripts]` for the entry point (`main.py` / `cli.py` at the root).
3. **Dependencies as extras.** 16 hard deps today; core needs 8 (fastapi,
   uvicorn, pydantic, aiosqlite, bcrypt, pyjwt, python-dotenv, pyyaml).
   `redis`/`aio-pika`/`aiokafka`/`asyncpg`/`aioboto3` become extras;
   `apscheduler` is already lazily imported with its own install message.
   `httpx` and `websockets` have no import anywhere — verify before keeping.
4. **The scaffolder** — `microcoreos new` replaces "clone the repo" as onboarding.

**NOT needed under this scope: a path resolver.** An earlier framing assumed
tools and domains would live in BOTH the wheel and the project, making every
`os.path.abspath("domains")` (twelve of them) resolve against only one root.
With everything but `core/` materialized there is a single root and CWD-relative
resolution stays correct. The resolver returns the day stabilized tools move
INTO the wheel — at which point it should hand back a **list** of roots, so the
twelve scanners are touched once and never again.

**Already paid for by other work:** discovery narrowed to `*_tool.py` /
`*_plugin.py` (Issue 41) means optional drivers are no longer imported at boot,
so a core installed without `redis` no longer reports a load error for a
transport nobody selected. That was a hard blocker for `uv add microcoreos`.

**Checklist (in this order — each step de-risks the next):**

- [x] **1. `[build-system]` + build the wheel.** ✅ hatchling,
      `packages = ["microcoreos"]`. The wheel holds exactly the 8 files of the
      package and nothing else. Two things the plan did not anticipate:
      - **Only one `__init__.py` was needed**, not one per package. Nothing
        else ships, and `tools/` / `domains/` are never imported as packages —
        the Kernel loads them file by file via `importlib`. That `__init__.py`
        is already the flat public API of step 4 (the five plugin-facing names),
        so the rename is now a `sed` over imports plus a folder move.
      - **The entry point is `microcoreos.cli:main`, not `cli:main`.** A top-level
        `cli.py`/`main.py` in the wheel would land in site-packages as modules
        named `cli` and `main` — the exact shadowing problem that forces the
        `core` rename. The CLI moved INTO the package; the root `main.py` and
        `cli.py` are 5-line shims, so `uv run main.py [--boot-tool db]` is
        unchanged and stays sacred. `microcoreos dev` == `uv run cli.py`.
- [x] **2. Dependencies as extras.** ✅ 16 hard deps → 9. Extras `[redis]`,
      `[postgres]`, `[kafka]`, `[rabbitmq]`, `[s3]`, `[scheduler]`, `[all]`;
      the dev group pulls `microcoreos[all]` since the suite exercises every
      swappable tool. Verification of the two suspects:
      - `httpx` → **dev group.** Its only 4 imports are tests driving the ASGI
        app through `ASGITransport`.
      - `websockets` → **kept in the base.** No `import websockets` anywhere,
        but it is uvicorn's WS protocol implementation: without it
        `HttpServerTool.add_ws_endpoint()` fails at runtime, not at import.
- [x] **3. Prove the wheel.** ✅ Clean venv, wheel installed with NO extra, the
      other directories copied in by hand (the step-6 scaffolder does not exist
      yet): boots with **zero load errors**, EventBus selects InProcessDriver,
      HTTP serves. Confirms Issue 41 paid off — no unselected transport is
      imported. It caught one real bug: **an installed console script does not
      put the CWD on `sys.path`** (`python main.py` does — sys.path[0] is the
      script's directory, but for a console script it is the venv's `bin/`).
      Every `import tools.*` failed and the Kernel still reported "System
      Ready". Fixed in `microcoreos/cli.py::_ensure_project_on_path`, plus a
      wrong-directory guard so an empty boot never passes for a healthy one.
      **Resolved 2026-07-27 — the scheduler moved to `extras/`.** A fresh
      install used to boot with `🚨 Tool 'scheduler' failed` +
      `DurableOneShotsPlugin aborted`, because the scaffold materialized a
      plugin whose tool was an extra. The rule that settles it: **a plugin
      cannot exist without its tool**, so an optional tool cannot leave a
      mandatory plugin behind. Either the tool becomes mandatory (apscheduler
      into the base) or the plugin becomes optional with it. Chose the second —
      it is what `extras/` already does for `chaos` (tool in
      `available_tools/`, its plugins in `available_domains/`).
      - `tools/scheduler` → `extras/available_tools/scheduler`
      - `domains/system/plugins/durable_one_shots_plugin.py` + its model and
        its migration → `extras/available_domains/scheduler/`
      - The dependency runs ONE way: `mv` the tool alone gives cron and
        in-memory one-shots; the domain is a second, independent `mv` that
        requires the first. The README documents both steps.
      - Boot is now clean with no extra installed, and `AI_CONTEXT.md` lost 39
        lines — the LLM-facing inventory no longer describes a tool that is
        not there.
- [x] **4. Rename `core` → `microcoreos`,** ✅ flat public API in
      `microcoreos/__init__.py`. 83 imports collapsed to two forms: the five
      plugin-facing names now come from `from microcoreos import ...` (75
      sites), and `kernel`/`container`/`registry`/`cli` keep their submodule
      address (8 sites). CI's syntax check and the docs moved with them.
      Two things the `sed` could not know:
      - **Inside the package, keep importing the defining submodule.** The
        flat re-export is the address for USERS; `container.py` doing
        `from microcoreos import ToolUnavailableError` is a package importing
        itself mid-initialization — it survives today only because `__init__`
        never reaches back into `container`.
      - `TestPublicApi` in `tests/core/test_core.py` now pins both halves: the five
        names are exported, and Kernel/Container/Registry are NOT — so the
        boundary cannot erode by accident.
- [x] **5. The template/linter files.** ✅ Smaller than feared: **no linter
      matches on the string `core`**. DiscoveryNaming matches AST base-class
      names (`BaseTool`/`BasePlugin`), DomainIsolation matches the `domains.`
      and `tools.` prefixes — both survive the rename untouched, and their
      fixtures were rewritten to the new import form so the tests prove
      detection against what plugins actually look like now. The only real
      template is `tools/context/authoring_guide.md` (2 occurrences); the
      "10 files" estimate counted comments. `AI_CONTEXT.md` regenerated by
      booting: it emits `from microcoreos import BasePlugin`. Boot is green,
      ToolDocDrift included.
- [x] **6. `microcoreos new` scaffolder.** ✅ `microcoreos/scaffold.py` (~150
      lines) + `tests/system/test_scaffold.py`. Decisions the checklist left open:
      - **Where the source comes from.** The template rides in the wheel as
        inert payload under `microcoreos/_template/` (hatch `force-include`),
        never imported from site-packages. In a checkout that directory does
        not exist and the repo root IS the template — one source of truth, and
        `new` is testable without building a wheel.
      - **The AI kit travels with it.** `AGENTS.md` points at `.agent/` and
        `docs/`; copying it alone leaves an agent reading dangling links, and a
        project with no agent rules is not this framework. `--no-ai-kit` opts
        out.
      - **`extras/` is materialized too** — missed on the first pass. Installing
        infrastructure here IS moving a folder, so a project without the swap
        catalog cannot perform the swap its own docs describe.
      - **`domains/users` and `domains/ping` stay behind**, per the plan. Worth
        knowing: `tools/auth` therefore ships in a fresh project with no login
        endpoint, since those plugins live in `domains/users`. Same shape as
        the scheduler question, opposite answer so far — either accept it
        (auth flavor is opinionated boilerplate) or add a `--with-auth`.
      - Refuses to overwrite an existing `tools/`/`domains/` without `--force`,
        and never touches an existing `.env` or `pyproject.toml` — so
        `uv add microcoreos && microcoreos new .` is a supported flow.
- [x] **7. End to end.** ✅ Clean venv → `uv pip install microcoreos` (wheel
      only, no extra) → `microcoreos new demo` → boots, migrations apply,
      `GET /system/status` answers with every tool `OK`. Then
      `pip install 'microcoreos[scheduler]'` → boot is completely clean.
      Caught the last packaging-only bug: **`load_dotenv()` searches upward
      from its CALLER.** In a checkout the caller was the root `main.py`, so it
      found the project's `.env` by accident; installed, the caller is
      `site-packages/microcoreos/cli.py` and the search walks the venv instead.
      A scaffolded project failed with `AUTH_SECRET_KEY is required` while
      holding a `.env` that sets it. Now loaded by explicit path
      (`_load_project_env`). Same shape as the `sys.path` bug in step 3: both
      are assumptions that only held because the entry point sat in the
      project.

The README roadmap bullet was aligned with this decision (2026-07-27): it used to
promise "Official tool packages — `microcoreos-redis`, `microcoreos-postgres`",
the package-per-tool model rejected above.

---

**Issue 34 — 🟢 ChaosControlPlugin: runtime fault injection (extras) — design 2026-07-12, shipped 2026-07-19**

✅ **Shipped complete** (`extras/available_domains/chaos/plugins/chaos_control_plugin.py`,
suite `tests/system/test_chaos_control.py`): tool faults (`down`/`slow`/`flaky`,
global and caller-scoped, via raw-method wrapping — zero core changes) AND
plugin pause/resume (`POST /system/chaos/off|on {plugin}`; a bare domain
prefix pauses the whole domain). Pause mechanics as designed: private
`_paused_owners` sets in the bus and http tools (NOT public API — the Issue
36 freeze holds), mutated only by the chaos plugin. One documented deviation
from the letter below: in_process deliveries are HELD (accumulate as pending
tasks, drain on resume) rather than dropped — uniform "backlog drains"
semantics on every rung; ephemerality is preserved at crash level. Durable
transports hold BEFORE ack, so the backlog accumulates broker-side (proven:
sqlite rows stay on disk while paused, drain in order on resume). Paused
owners' HTTP endpoints answer 503 with routes still mounted. Original design:

The chaos extras cover boot-time failure; what's missing is **runtime** chaos
for live experiments (MicroCoreBench drives it, but any operator can). Two
interception points, one tiny generic primitive each:

- **Plugins → pause/resume at the Bus** (NOT unsubscribe — that loses the
  callback for re-enabling and collides with auto-unsubscribe). The bus
  already names every subscription `domain.Class.method`: add a paused-owner
  set the delivery loop checks. The right semantics fall out of each driver
  for free: `in_process` drops the delivery (honest ephemeral), durable
  groups simply stop claiming rows → **backlog accumulates while paused,
  drains on resume** — the "turn payment off under traffic, watch it
  recover" experiment with zero queue logic written. HTTP side: the paused
  owner's endpoints answer 503 (routes are not unmounted — simulates the
  service being down for callers).
- **Tools → fault modes at the ToolProxy**, the universal interception seam
  (metrics/spans/DEAD-marking already live there): `down` (every call
  raises), `slow` (injected sleep), `flaky` (fail N%). This exercises the
  plugins' real Safe-Error paths, trips the registry's existing DEAD
  marking, and lights up tool_health/the City — every defense reacts as if
  real, because for them it IS real.

`ChaosControlPlugin` (extras/available_domains/chaos/, never active by
default) exposes it: `POST /system/chaos/{off|on}` {plugin},
`/system/chaos/latency` {event, seconds}, `/system/chaos/fail` {event, rate},
`/system/chaos/tool` {name, mode}. Every chaos action publishes a
`system.chaos.*` event so experiments appear causally in the trace tree.

**Zero core changes.** The paused set is a Bus feature (`tools/event_bus/` —
a tool, not core), the 503s are an http-tool feature, and tool faults need no
proxy change: the chaos plugin takes `container` (the sanctioned meta-plugin
introspection precedent) and wraps raw tool methods via `get_raw_tools()`,
keeping originals for restore — calls still traverse the ToolProxy, so DEAD
marking, metrics and spans react unmodified. All monkey-patching stays inside
the deletable extras plugin. A first-class fault flag in the ToolProxy (same
family as its existing DEAD marking) is the promotion path ONLY if wrapping
proves fragile — the usual decision-log criterion. Auto-unsubscribe interplay
is free observability: sustained injected failures end in
`system.subscriber.dropped` after 5 final failures, causally traced.

---

**Issue 41 — ✅ Module identity, tool modularization & discovery by convention (2026-07-27 session)**

Four changes, in dependency order — each one was the precondition for the next.

- **Loader imports by name, not by path.** `_load_modules_from_dir` built module
  objects with `spec_from_file_location` under a synthetic `mod_*` name. Any file
  the Kernel loaded AND someone imported normally therefore existed **twice**,
  with two distinct copies of every class it defined — `isinstance` between them
  False. The codebase had already grown two workarounds for this (a warning in
  the driver contract saying "do NOT import EventEnvelope yourself", and an
  `isinstance` replaced by MRO name-matching in `_driver_from_env`); both are
  now deleted. `importlib.import_module` shares one object through `sys.modules`,
  so the class a plugin imports is the class the Kernel discovered.
- **The four large tools split** (13 modules where there were 4 files), safe only
  after the above: `sqlite_tool` 986→591 (`errors`/`transaction`/`migrations`),
  `http_server_tool` 907→558 (`context`/`pipeline`), `event_bus_tool` 591→455
  (`envelope`/`drivers`), `context_tool` 527→161 (`scanners`/`renderers`).
  Pure moves, verified line-by-line; `AI_CONTEXT.md` byte-identical afterwards.
  Symbols external code imported from the old addresses are re-exported (marked
  `# noqa: F401` — ruff cannot see that four drivers import `EventBusDriver`
  from `event_bus_tool` by that exact path, and `--fix` would delete them).
- **Discovery narrowed to `*_tool.py` / `*_plugin.py`.** The walker imported 22
  files under `tools/` to find 11 tools. Importing a file that CANNOT hold a tool
  is not free: `redis_streams_driver.py` imports `redis` at module level, so a
  core without redis installed reported a boot error for a transport nobody
  selected — a hard blocker for Issue 39. The convention holds perfectly across
  the repo (11/11 tools, 28/28 plugins, extras included) and was already relied
  on by `tests/helpers/active_db.py` for this exact reason. Note the filter is
  the FILENAME, not "imports base_tool": `redis_streams_driver.py` and
  `sqlite/errors.py` both import from `core.base_tool` (for
  `ToolUnavailableError`) and are not tools.
- **`DiscoveryNamingLinterPlugin`** — the mandatory other half: a misnamed file
  is no longer an error, it is simply never found, and the only runtime symptom
  is a plugin reporting `Missing tools: x` from a domain nobody touched. AST
  scan over `tools/`, `domains/` and `extras/` (extras included because those
  files are activated by moving them in — a wrong name there detonates the day
  someone swaps it). Verified live: renaming `state_tool.py` drops the Kernel
  from 11 tools to 10 in silence, and the linter names it.

Also fixed on the way, pre-existing and unrelated: the `SQLiteDriver` queue
(`EVENT_BUS_SQLITE_PATH`, default `event_bus_queue.db` at the repo root) leaked
state between runs — under `EVENT_BUS_DRIVER=sqlite` the second run of the bus
suite failed on rows left by the first. 11 test files built a bare
`EventBusTool()`, so the fix is one autouse fixture in a new `tests/conftest.py`
rather than per-file patches. No test depended on the leftover to pass.

**Issue 1 — ✅ Domain-level AI_CONTEXT.md**
Each domain is summarized in the auto-generated `AI_CONTEXT.md` (tables,
endpoints, events emitted with payload keys, events consumed, dependencies,
plugins). The AI reads this instead of code to know what exists.

**Issue 2 — ✅ Standardized validation pattern**
`pydantic.Field` with explicit constraints is the only accepted pattern for
request schemas. Documented in `INSTRUCTIONS_FOR_AI.md`.

**Issue 11 — ✅ Normalize 422 validation errors to standard envelope**
`RequestValidationError` handler in `HttpServerTool.setup()` returns the
standard `{"success": bool, "error": ..., "details": ...}` envelope. All HTTP
responses use the same envelope regardless of error type.

**Issue 12 — ✅ Scheduler tool**
Implemented as `tools/scheduler/` (APScheduler backend, zero infra). API:
`add_job(cron_expr, callback)`, `add_one_shot(run_at, callback)`,
`remove_job(job_id)`, `list_jobs()`. Swappable to Celery beat via the same
replacement standard. See Issue 19 for the N-replica singleton pattern.

**Issue 13 — ✅ Rate limiting (resolved as a pattern, NOT as a tool — decision 2026-06-10)**
Decision: **no tool is created**. The problem splits into two layers and neither needs one:
- **Volumetric/anonymous (per-IP, anti-abuse, DDoS)** → edge infrastructure
  (nginx/gateway/CDN), not the monolith's concern. Documented in `docs/ELASTIC_DEPLOYMENT.md`.
- **Identity-aware (per user/API key/plan)** → business policy on top of a
  primitive that already exists: `state.increment(key, ttl=window)` → 429 +
  `Retry-After`. Pattern documented in `INSTRUCTIONS_FOR_AI.md` ("Rate Limiting
  Pattern"). With RedisStateTool swapped in, the limit is distributed for free.

The proposed tool (`check(key, limit, window)`) was ~5 lines over `state` and
would have duplicated its Redis backend. The only uncovered value: sliding
window — promote to a tool only if a real use case demands it.

### Contracts & Governance

**Issue 5 — ✅ Event contract validation**
`EventContractLinterPlugin` (devtools domain): static AST cross-check of every
publish site's payload keys vs every subscriber's required keys, exposed at
`GET /system/lint`. Extended by Issue 29 (typed payloads).

**Issue 15 — ✅ Architecture linters (Anti-Drift + Isolation)**
- **Domain Isolation Enforcer**: no cross-domain imports, verified at boot.
- **Anti-Drift Guard**: every public Tool method must be documented in
  `get_interface_description()`; discrepancies mark the Tool with `WARNING`.
- **Split one-rule-per-plugin (2026-07-27 session)**: shipped as a single
  `ArchitectureLinterPlugin` accumulating four checks (15, 26, 27) until
  Issue 37 would have made it five. Now `domain_isolation_`, `tool_doc_drift_`,
  `table_ownership_`, `route_collision_` and `field_divergence_linter_plugin.py`
  in devtools — same registry keys, so `GET /system/lint` is unchanged. Each
  declares only the tools it uses (only the route linter takes `http`) and one
  failing check no longer takes the other four down with it. Shared file
  enumeration in `domains/devtools/lint/plugin_sources.py`.
  Tests: one file per linter, `tests/test_*_linter.py`.

**Issue 29 — ✅ Typed event payloads, schema catalog & plan format v2 (2026-07-11 session)**
- **Convention**: the publisher owns the event contract — `XxxPayload(BaseModel)`
  inline in the publisher plugin, published via bare `.model_dump()`; consumers
  are tolerant readers (re-declare only the fields they need, never import the
  publisher's model). Documented in `INSTRUCTIONS_FOR_AI.md` + AI_CONTEXT rule 11.
- **Linter**: resolves `Payload(...).model_dump()` statically (direct and via
  variables); raw-dict publishes flagged `UNTYPED_PAYLOAD` (info, advisory);
  `model_dump(args)` honestly reported as `UNKNOWN_PAYLOAD`.
- **`GET /system/events/schemas`**: event → JSON Schema catalog from the real
  Pydantic classes — the Schema Registry seed for the Kafka driver (Issue 18).
- **Plan format v2** (`docs/PARALLEL_DEVELOPMENT.md`): flows declare happy path
  + sad-path checklist per link (retries, idempotency, DLQ watcher,
  `atomic_with_db` → Issue 28, compensation → saga) and an e2e chain test
  (helper `tests/helpers/trace_chains.py`). Four workflow levels in
  `.agent/workflows/`: feature-plan, new-domain, multi-domain-plan, new-tool.

**Issue 26 — ✅ Route-collision linter (2026-07-17 session)**
Implemented inside the architecture linter (its own plugin since the
2026-07-27 split, see Issue 15). Timing was the
real problem: plugins' `on_boot()` run concurrently (`asyncio.gather`), so a
plugin-side check would race other plugins' `add_endpoint()` calls. Solution:
a **generic** http-tool capability, `register_pre_mount_hook(hook)` — the tool
invokes registered hooks once from its own `on_boot_complete()` (the first
point where every plugin has definitely registered), passing the buffered
endpoints as `{method, path, owner}` (owner = the `domain.ClassName` identity
the Kernel stamps on every plugin). Duplicate `(method, path)` → warning
listing both owners; registry metadata `route_collisions`; surfaced in
`GET /system/lint`. Zero core changes. Runtime backstop for plan rule 1.

**Issue 27 — ✅ Table-ownership linter (2026-07-17 session)**
Also an architecture linter (its own plugin since the 2026-07-27 split, see
Issue 15): scans `domains/*/migrations/*.sql` at
boot, extracts `CREATE TABLE [IF NOT EXISTS]` names, warns when one table is
declared by more than one domain (the second `IF NOT EXISTS` silently no-ops
against the wrong schema). Registry metadata `table_ownership_warnings`;
surfaced in `GET /system/lint`. Runtime backstop for plan rules 2/14 — it
covers code written outside the plan workflow, which the plan validator
cannot see.

**Issue 37 — ✅ Field-constraint divergence linter (built 2026-07-27, closed 2026-07-28)**

`1 file = 1 feature` trades duplication for locality — a deliberate and correct
trade when the writer is an agent: rewriting 120 lines is cheaper than
refactoring an abstraction, and "change it in 40 places" stopped being work the
moment traversing the repo became a 10-minute job. **The residual cost is not
effort, it is detection**: nobody greps for a rule they forgot exists.

The failure mode is **semantic divergence** — not duplicated code, a duplicated
*decision* that later drifts apart:

- three plugins validate price as `gt=0`, `ge=0` and `> 0`; three tests pass;
  the system now holds three definitions of "valid price" and nothing is red.
- two consumers of the same event re-declare tolerant-reader models, one reads
  `total_cents`, the other `total`; the publisher renames; one breaks loudly,
  the other silently takes a default.

**Why no existing check sees it:** a black-box test proves that a feature
honors ITS contract, never that two features honor THE SAME contract.
Divergence is a property *between* features, so no per-feature test can observe
it, by construction rather than by omission. This is the same species as
**Issue 26 (route collisions)** and **Issue 27 (table ownership)** — cross-feature
invariants, invisible from inside any single plugin, and both solved the same
way. This is the third one.

**Mechanism** — `FieldDivergenceLinterPlugin` (own plugin: the linters were
split one-rule-per-plugin, see Issue 15), static AST scan of
`domains/*/plugins/*_plugin.py` at boot, same timing as the table-ownership
scan (no pre-mount hook needed: unlike routes, nothing here is registered at
runtime). Collect every `pydantic.Field(...)` constraint per field name, group,
and warn when the same name carries different constraints. Registry metadata
`field_divergence_warnings`; surfaced in `GET /system/lint`; warn-only at boot,
hard gate in CI (Issue 33). Zero core changes.

**Status: scope 2 shipped** (request/response fields compared within a domain —
`tests/linters/test_field_divergence_linter.py`). Scopes 1 (event payload keys compared
fleet-wide, pairs with the event-contract linter) and 3 (opt-in list of
system-wide names) remain open — each needs its own comparison rule, and
shipping them as one would blur exactly the scoping distinction above.

**The design constraint that decides whether it is useful or noise:** a shared
NAME is not a shared CONCEPT — `name` in users and `name` in products differ
legitimately, and a naive global comparison produces enough false positives to
be ignored, which is worse than not shipping it. Scoping rule:

1. **Event payload keys → compare fleet-wide.** Here the contract genuinely IS
   shared (the publisher owns it, Issue 29), so any divergence is a real defect
   and pairs with the existing event-contract linter.
2. **Request/response fields → compare within a domain only.** Same domain,
   same name, different constraints is almost always a mistake.
3. **Cross-domain request fields → silent by default**, opt-in via an explicit
   list of names declared as system-wide (`email`, `price`, `currency`...).

Out of scope by decision: divergence expressed in SQL predicates
(`deleted_at IS NULL` vs `status = 'active'` for "active user"). That is semantic
equivalence of queries, not constraint comparison — a different and much harder
problem, and pretending to cover it would make the linter dishonest about what
it checks.

**Trigger:** the first time two plugins are found disagreeing on a constraint in
a real project. The `Examples/` products are where that shows up — same
discipline as every other issue here: the pattern is specified now, the code
ships when a real chain demands it.

**Closed 2026-07-28.** It was built and the flag was never lowered:
`domains/devtools/plugins/field_divergence_linter_plugin.py` (178 lines),
10 tests, and it runs green on every boot. The waiver mechanism shipped
with it — a declaration carries `json_schema_extra={"divergence_ok": ...}`
with a reason, drops out of the comparison rather than silencing the field,
and an empty reason is not honoured. That is what let a scaffolded project
boot with zero warnings instead of a permanent one nobody would read
(docs/internal/TECH_DEBT.md item 1).

**Issue 35 — ✅ Plan `contract:` for phase-0 tools & checklist coverage (2026-07-17 session)**
- **`contract:`** — a NEW tool in `phase_0.tools` now declares its method
  signatures + return shapes in the plan, so the phase 0 author writes it
  1:1 ("never inventing a method" — same rule as `columns:` for migrations).
  It is a handoff, not a second source of truth: after the phase 0 boot,
  `AI_CONTEXT.md` carries the real interface and is what the wave reads.
  Replacements declare no contract (the reference tool's header spec is the
  contract). Documented in `docs/PARALLEL_DEVELOPMENT.md` + `new-tool.md`.
- **Validity rule 15 (advisory)** — `POST /system/plan/validate` now
  cross-checks every task path the plan declares against the execution
  checklist (`plans/active_plan.md`): a task missing from the checklist is
  never dispatched and the checklist reaches all-`[x]` with the feature
  silently absent. Path-or-basename matching, and the check skips itself for
  checklists sharing zero paths with the plan (drafts). Zero new procedures —
  it rides the validate call the orchestrator already makes.

**Issue 32 — ✅ Plan format v3 (crash points, proofs) & mechanical plan validator (2026-07-12 session)**
- **Format v3** (`docs/PARALLEL_DEVELOPMENT.md`): per-feature `db:` persistence
  contract (black-box contract = input + output + storage + events); per-flow
  `durability` (the "in-flight event dies with the process" crash point —
  connects the plan to the Issue 31 driver ladder), `sad_path_test` and
  `rpc_links` (timeout is RPC's one failure mode); per-link `idempotency_test`
  (the double-delivery proof — "idempotent" was a claim, at-least-once rests
  on it). Idempotency now mandatory where `retries > 0` OR the flow is durable
  (durable transports re-deliver after a crash even with zero retries).
- **Crash-test split**: redelivery is proven once by the transport
  (kill-and-reboot suite, Issue 31); flows prove only their side — idempotency.
  No feature ever writes a kill test. Sad-path chains assert via the existing
  helper: `_dlq.<event>` publishes inside the failing delivery's context, so
  `assert_chain(tree, ["x", "_dlq.x"])` works with no new machinery.
- **Validator**: `PlanValidatorPlugin` (devtools domain) —
  `POST /system/plan/validate` takes the plan (YAML or JSON) and executes all
  15 validity rules against the plan AND the live system (routes via AST scan,
  tables via migrations, events via registry metadata + bus subscribers,
  driver via env). ERRORS = invalid plan; WARNINGS = advisory (e.g. durable
  flow on `in_process`). "Mechanically checkable" became literal: the
  orchestrator validates with a tool, not with attention.

---

**Issue 33 — ✅ devtools domain & CI lint gate (2026-07-12 session)**
- **The split**: `domains/system/` was hosting two families — runtime
  observability (traces, metrics, status, streams: production needs these)
  and development tooling (both linters, the schema catalog, the plan
  validator: the AI/orchestrator needs these). The second family moved to
  `domains/devtools/` — a deployment that wants a smaller surface deletes the
  folder and nothing else changes (each plugin is one self-contained file).
  Routes keep their documented `/system/*` paths (the contract is the path,
  not the folder); registry metadata moved to the `devtools` key.
- **Advisory at boot, hard gate in CI** — made literal on both halves:
  the full pytest suite already gates event contracts and now also domain
  isolation over the real repo (`test_real_repo_has_no_isolation_violations`);
  the `smoke-boot` CI job now curls `/system/lint` on the booted system and
  fails the pipeline on any arch violation, tool drift, or event contract
  warning (drift needs live tools, so the smoke boot is where it can gate).
  Boot linters stay warn-only by design: a running system is never blocked.

---

### Transport & Durability

**Issue 18 — 🟢 Distributed Event Bus drivers (Redis Streams ✅ / Kafka ✅ / RabbitMQ ✅)**

The EventBusTool is NOT rewritten: the `EventBusDriver` interface is implemented
(transport only). Retries, DLQ, RPC and tracing are agnostic and live in the Bus.

✅ **RedisStreamsDriver** (`tools/event_bus/redis_streams_driver.py`):
- Zero-code activation: `EVENT_BUS_DRIVER=redis_streams`. N replicas against the
  same Redis share transport; `group=` is a real consumer group
  (exactly-one-consumer across the fleet).
- Passes the full parity suite (`test_event_bus_broker_parity.py`, now
  parameterized over both transports) + its own distributed tests
  (`test_redis_streams_driver.py`: 2 instances, cross-delivery, groups).
- Validated end to end: real system booted with the driver, `user.created`
  → WelcomeService traveling through Redis with the causal tree intact.
- Design note: `EventBusDriver.bind()` now also injects the Bus's
  `EventEnvelope` class — drivers must NOT import it (the Kernel loads modules
  by path and an imported copy is a different class to Pydantic).

✅ **RabbitMQDriver** (`extras/available_tools/rabbitmq/rabbitmq_driver.py`):
groups → competing-consumer queues, at-least-once via
ack-after-handler. Parity suite: `test_event_bus_rabbitmq_parity.py`.
Activation: drop the file into `tools/event_bus/` + `EVENT_BUS_DRIVER=rabbitmq`
(driver discovery is generic since 2026-07-11 — file placement IS the
installation, same swap standard as the db tool).

✅ **KafkaDriver** (`extras/available_tools/kafka/kafka_driver.py`, 2026-07-19):
groups → real Kafka consumer groups (commit-after-handler, at-least-once),
`key` → partition key (per-key strict ordering — unkeyed events are
round-robined across partitions, so cross-event order is not total),
RPC replies → shared topic `bus.__replies__`
(one topic per request would litter the cluster; the driver filters by exact
event name). Broadcast subscriptions are standalone consumers (no group, no
join latency). Parity suite: `test_event_bus_kafka_parity.py`; broker for dev
in `dev_infra/docker-compose.yml` (single-node KRaft). Activation: drop the
file into `tools/event_bus/` + `EVENT_BUS_DRIVER=kafka`. Since Issue 30
(2026-07-19) it claims `delay: native` — delayed envelopes are parked in
`bus.__delayed__` and promoted by a fleet-wide scheduler group, so a
publisher crash never loses them.

**Update 2026-07-11**: the Kafka driver's contract side is already prepared —
`GET /system/events/schemas` serves the full catalog (event → JSON Schema,
generated from the publisher-owned payload models). That catalog is exactly
what the broker's Schema Registry ingests, with zero plugin changes.

---

**Issue 30 — 🟢 Driver capability negotiation (shipped 2026-07-19: mechanism + native delay)**

The contract is semantic; the implementation is free: a driver may implement
any Bus semantic with its broker's native machinery, as long as the parity
suite still passes (the same rule that lets the SQLite tool translate `$1`
to `?`). The Bus implements everything in software as the universal
fallback; drivers CLAIM capabilities and take over:

```python
class RabbitMQDriver(EventBusDriver):
    capabilities = {"delay": "native", "retries": "in_bus", "dlq": "in_bus"}
```

✅ **Shipped**: `EventBusDriver.capabilities` (default: everything `in_bus`),
the Bus consults the claim (`_transport_publish`), and the ACTIVE TRANSPORT
line in `get_interface_description()` surfaces the active driver's claims in
the manifest. **`delay` is now native in every durable/distributed driver** —
the crash-window (a publisher dying mid-sleep lost the event) is closed:
- SQLite: `due_at` row (already was — it defined the pattern).
- Redis Streams: parked in the ZSET `bus:__delayed__`, promoted by an atomic
  Lua script every replica polls.
- RabbitMQ: TTL wait-queue + dead-letter-exchange per delay value (stock
  broker, no plugins).
- Kafka: parked in `bus.__delayed__`, promoted by a fleet-wide scheduler
  group (holds uncommitted with paused polls — arbitrarily long delays
  without group eviction).
Each proves it with a `test_delayed_survives_publisher_death` (publisher
shuts down mid-delay; a surviving replica still receives), plus the parity
tests `test_delayed_delivery` / `test_capabilities_declared` for all drivers.
`retries`/`dlq` stay `in_bus` **by design**: they are already crash-safe
(drivers ack only after handler + retries finish), so native retry topics /
DLX routing remain optional future work, not a gap.

Native implementations per broker, same observable contract:

| Bus semantic | Software fallback | Native option | Gain |
|---|---|---|---|
| `delay=n` | driver-side sleep | Rabbit delayed exchange / Kafka scheduler topic | delay survives a crash |
| `retries/backoff` | in-process re-execution | Kafka retry topics / Rabbit nack+DLX+TTL | retries survive replica death |
| DLQ `_dlq.<event>` | Bus publishes an event | Rabbit dead-letter exchange routing to `_dlq.*` | broker mechanics, same event |
| at-least-once | — | ✅ already native (XAUTOCLAIM / unacked redelivery) | the precedent |

Non-negotiable: drivers must keep reporting attempts/outcomes to the Bus so
causal tracing never goes blind, and every native claim must pass the parity
suite. Broker-exclusive features enter ONLY through: (a) universal hints
(best-effort, degraded where unsupported — like `priority` today), (b) driver
env config (like `RABBITMQ_PREFETCH`), or (c) promotion to a Bus semantic
with a software fallback. Never a plugin talking to the broker directly.

---

**Issue 36 — 🟢 Bus contract freeze (admission rule) + deferred driver optimizations**

The Bus semantic contract is **CLOSED**. It already covers a full broker
feature set (groups, retries, DLQ, RPC, TTL, delay, priority, key, broadcast,
tracing, poisoned-handler escalation); anything new must enter as:
(a) a **plugin-layer composition** (like the Outbox, Issue 28 — never Bus code),
(b) a **driver capability claim** over an EXISTING semantic (Issue 30), or
(c) a new ROADMAP issue arguing why it must be universal — accepted only by
    consciously updating `test_public_contract_frozen` in the parity suite,
    which pins `EventBusTool`'s exact public surface, in the same commit.
This is the structural answer to god-component drift: the public API cannot
grow by accident, and driver complexity stays quarantined (a driver cannot
add API surface; worst case its file is deleted).

**What qualifies (admission criterion, written 2026-07-25):**

> **If a real broker exposes it, it is contract. If we invented it, it needs a
> use case.**

The rule exists because "nothing uses it today" is NOT evidence in a framework.
A product has users; a framework has a contract, and the contract is honored
*before* anyone exercises it — waiting for a real consumer means never being
able to offer anything. So the burden of proof splits by origin:

- **Market-validated semantics** (`priority` in RabbitMQ, `key` in Kafka/SQS,
  RPC in half the ecosystem, groups, TTL, delay, DLQ): the market already
  proved they are needed, and their existence is what makes a **parity suite
  writable at all** — there is a reference implementation to compare against.
  These stay even with zero local consumers. They are not dead code; they are
  an unexercised contract.
- **Invented capabilities** (no analog in any broker): must justify themselves
  with a real use case, because there is no external reference and therefore no
  parity suite that could define "correct". Absent one, they get removed.

Corollary on how a use case is found: **not with `grep`.** The question
"does anyone need RPC?" is answered by building a complex enough product to
find out (e.g. Uber-style surge lookup for a zone *before* quoting a ride —
the caller needs the answer to continue, so publish-and-forget does not
serve it), not by scanning the current repo for callers. That is what the
`Examples/` products are for; `07-microride` is the one that exercises the
widest slice of the contract.

First application of the rule, in reverse (2026-07-19): **wildcard
subscriptions (`subscribe("*")`) were REMOVED** — capability without a use
case, and, by the criterion above, an *invented* one: no broker exposes
"subscribe to everything" as a client primitive, so there was no reference
contract and no parity suite that could pin it. In-process observation is `add_listener()`'s job (publish-side sink,
zero transport cost — how the event viewer/traces/delivery monitor already
work); distributed audit belongs to the broker's own tooling (an external
consumer on the topics/streams). Removing it also removed the firehose
double-write every distributed driver paid on EVERY publish (Redis `bus:*`,
Kafka `bus.__all__`) and the `is_wildcard` plumbing across the Bus and all
four drivers. If a fleet-wide observer plugin ever becomes real, the parity
suite documents exactly what to restore.

Deferred driver optimizations — each with its written trigger, none is a gap:
- **Kafka delay bucket topics** (`bus.__delayed__.{bucket}`): removes the
  head-of-line wait between different delay values that hash to the same
  partition. Trigger: a real workload mixing long and short delays at volume.
- **Kafka multiplexed RPC replies**: one persistent reply consumer per
  instance routing by correlation_id, instead of one ephemeral consumer per
  request. Driver-internal, zero Bus changes. Trigger: RPC over Kafka
  becomes a hot path.
- **Idempotency helper**: an opt-in plugin-layer decorator deduplicating by
  `envelope.id` (state-tool backed). Plugin layer, NOT Bus code (rule (a)).
  Trigger: the first handler whose natural implementation is not idempotent.

---

**Issue 31 — ✅ SQLiteDriver: durable event transport for the single-process monolith (2026-07-11)**
`tools/event_bus/sqlite_driver.py` — the elastic ladder's missing rung:
`in_process` (fast, ephemeral) → `sqlite` (durable, one node) →
`redis_streams`/`rabbitmq`/`kafka` (distributed). Activation:
`EVENT_BUS_DRIVER=sqlite` (generic driver discovery).
- Queue in **its own database file** (`EVENT_BUS_SQLITE_PATH`, default
  `event_bus_queue.db`), NEVER the business DB: the driver owns its
  connection like the Redis driver owns its client. Sharing the business
  file buys nothing (SQLite transactions are per-connection → no atomicity)
  and costs single-writer contention. This file is the embedded equivalent
  of a broker's log — it disappears when the transport is swapped to Kafka.
  Commit→publish atomicity remains the Outbox's job (Issue 28).
- Delays stored as `due_at` → **a pending delay survives a restart** and
  fires at its stored due time. Rule of thumb unchanged: `delay=` for
  operational pauses, `scheduler.one_shot.schedule` for scheduled business acts.
- Ack-after-handler (DELETE only after the handler and its Bus retries
  finish); rows claimed by a dead process reset to pending at boot →
  **crash mid-handler = redelivery**, at-least-once, idempotency already
  required by the bus contract. Groups outlive consumers (backlog drains on
  resubscribe), competing consumers claim rows atomically, broadcasts/RPC
  replies are deliberately in-memory only.
- Proven: full parity suite parameterized over all three transports +
  kill-and-reboot tests (`tests/tools/sqlite/test_sqlite_driver.py`), and the real
  system booted on it end to end (`user.created` → WelcomeService with the
  causal tree intact, queue drained to zero).
- Documented trade-off: `EVENT_BUS_SQLITE_SYNCHRONOUS=FULL` (default) is an
  fsync per commit — durability over raw throughput, opt-in by design.

### Observability

**Issue 6 — ✅ Proactive tool health check** — health-check plugins can override
status via `registry.update_tool_status()`; reactive detection via ToolProxy
(hybrid policy: `ToolUnavailableError` → DEAD immediately, otherwise 5 strikes).

**Issue 7 — ✅ Tool call duration tracking via ToolProxy** — every tool method
call timed; `registry.get_metrics()` + real-time sinks.

**Issue 8 — ✅ Real-time causal tree via SSE** — `GET /system/traces/stream`
(`domains/system/plugins/system_traces_stream_plugin.py`).

**Issue 9 — ✅ OpenTelemetry integration** — `OTEL_ENABLED=true`; every tool
call gets a span via ToolProxy; per-tool driver instrumentation optional.

### Path to Industrial Grade (2026-06-10 session)

> Conclusion of the analysis: the foundation is solid; what's missing are
> **additions, not surgeries**. The replacement specifications are already
> written in each tool's header.

**Issue 17 — ✅ RedisStateTool (first real tool swap)**
Implemented in `extras/available_tools/redis_state/` with `name = "state"` (in
extras/, NOT tools/: the Kernel auto-discovers everything under `tools/` and
two tools with the same name silently overwrite each other — activation is
moving it in, PostgreSQL-style).
- Follows the async + TTL contract from the `tools/state/state_tool.py` header.
- Parity suite: `tests/tools/state/test_state_parity.py` — the same battery runs
  against the in-memory impl and against real Redis; Redis added as a CI service.
- Swap validated end to end: login throttle against real Redis (counter +
  15-min TTL + 429).

**Issue 19 — ✅ Scheduler singleton + jobs via the bus**
- `SCHEDULER_ENABLED=true` (default) → "beat" role; `false` in worker replicas:
  jobs register identically everywhere but fire only in the beat.
- Pattern: the job publishes to the bus and workers consume — automatic groups
  guarantee exactly-one-consumer across the fleet.
- ✅ Durable one-shots: NOT in the tool (**a tool never uses other tools** —
  the composition precedent Issue 28 follows): `DurableOneShotsPlugin` (system
  domain) persists (run_at, event, payload) and a per-minute beat cron publishes
  the due ones. Any domain schedules via `bus.request("scheduler.one_shot.schedule", ...)`.

**Issue 20 — ✅ Migrations flag for CI/CD**
In production, migrations NEVER run in the replicas. They run as a pipeline
step, in a SINGLE instance, under explicit human supervision.
- `DB_AUTO_MIGRATE=true` (default) → dev behavior; `false` in production replicas.
- Pipeline entry point: `DB_AUTO_MIGRATE=true uv run main.py --boot-tool db`
  (`Kernel.boot_tool()` is generic — the kernel knows nothing about migrations).

**Issue 21 — ✅ Roles as users-domain data (Identity-Aware Authorization)**
Roles are business data of the `users` domain, not `auth` infrastructure.
JWT claims for general use + fresh DB check for critical operations (hybrid
rule, documented in `INSTRUCTIONS_FOR_AI.md`). Tests: `tests/test_roles.py`.

**Issue 22 — ✅ Tool parity (Contract Parity Rules)**
Every replacement tool MUST pass the parity suite of its reference
implementation. Formalized in `INSTRUCTIONS_FOR_AI.md`; canonical suites for
`state` and `event_bus`. Workflow: `.agent/workflows/new-tool.md`.

**Issue 25 — ✅ Elastic deployment guide**
`docs/ELASTIC_DEPLOYMENT.md`: the three stages (SQLite dev → PostgreSQL single →
N replicas), tool swaps, per-replica env checklist, edge layer, and the
verification procedure for the elastic setup.

### Replicas of the same monolith (2026-06-10 session, part two)

**✅ Automatic consumer groups (stable callback identity)**
`subscribe()` without `group=` derives a stable group from the callback
identity including its module — replicas derive the same group (each event to
exactly ONE replica), distinct plugins get their own copy. `broadcast=True`
for instance-local concerns. Validated with 2 real replicas.

**✅ At-least-once delivery in the Redis Streams driver**
XACK happens AFTER the handler (and its retries) finishes; if a replica dies
mid-handler another replica reclaims via XAUTOCLAIM (idle >
`EVENT_BUS_CLAIM_IDLE_MS`). Handlers must be idempotent (bus contract).

### HTTP Security Hardening

**Issue 51 — ✅ Explicit trusted proxies for context.client_ip**
- Shipped. `tools/http_server/pipeline.py` implements right-to-left traversal of
  `X-Forwarded-For` with explicit CIDR and IP trust checking (`HTTP_TRUSTED_PROXIES`).
- Wildcard `*` supported for zero-friction local development (e.g. Vite dev server, Docker bridge),
  with console security warning emitted if exposed on `0.0.0.0` with `*`.
- Generic `HTTP_CUSTOM_CLIENT_IP_HEADER` allows trusted reverse proxies / CDN headers
  (e.g. `X-Real-IP`, `True-Client-IP`) without vendor-specific code in core or tools.
- Uvicorn configured with `proxy_headers=False` to preserve socket peer integrity and
  keep MicroCoreOS as the sole authority for client IP resolution.
- Tests: `tests/tools/http_server/test_trusted_proxies_and_ws_origin.py`.

**Issue 48 — ✅ Configurable WebSocket Origin policy (HTTP tool only)**
- Shipped. Implemented `HTTP_WS_ORIGIN_POLICY=off|allowlist`, `HTTP_WS_ORIGINS`,
  and `HTTP_WS_ALLOW_MISSING_ORIGIN=true|false` in `HttpServerTool.setup()` and pipeline.
- In `allowlist` mode, unauthorized origins are closed immediately with WebSocket code
  1008 (Policy Violation) before the handshake acceptance, auth validator, or user callback.
- Enforces strict canonical origin normalization (`scheme://host[:port]`), rejects wildcards
  and `null` origins in allowlist mode.
- Tests: `tests/tools/http_server/test_trusted_proxies_and_ws_origin.py`.

### Lifecycle & Tool Hardening

**Issue 49 — ✅ Tool-owned cleanup when setup fails**
- Shipped. Implemented lifecycle teardown contracts in `SqliteTool`, `PostgresqlTool`,
  `EventBusTool`, `RedisStreamsDriver`, and `RedisStateTool`.
- If `setup()` fails (e.g. during connection, PRAGMAs, migrations) or is cancelled via
  `asyncio.CancelledError`, resources acquired (database connections, connection pools,
  background tasks, redis clients) are released immediately via `shutdown()` before
  propagating the original exception.
- Cleanup errors during teardown are reported separately without masking the original
  failure, and `shutdown()` methods are strictly idempotent and safe on partial initialization.
- Tests: `tests/tools/test_tool_setup_cleanup.py`.

**Issue 50 — ✅ Derive tool signatures; retain human-written semantics**
- Shipped. `renderers._generate_tool_signatures(raw_tool)` introspects real public methods
  on raw tools (bypassing generic `ToolProxy` wrappers), deriving canonical Python method
  signatures with parameter names, defaults, keyword-only args, and return annotations.
- Embedded as a dedicated `**Public Signatures:**` block in `AI_CONTEXT.md` per tool while
  retaining full authored semantics, examples, and replacement notes from
  `get_interface_description()`.
- Excludes private methods (`_*`) and lifecycle plumbing (`setup`, `shutdown`, etc.).
  Opaque callables report `<signature unavailable>` without inventing false signatures.
- Tests: `tests/tools/context/test_tool_signatures.py`.

**Issue 46 — ✅ Close the absolute tool-import spelling gap**
- Shipped. `DomainIsolationLinterPlugin._scan_file()` now applies the no-hardcoded-tool-import
  rule equally to both `ast.Import` (`import tools.x`, `import tools.x as y`, `import tools`)
  and `ast.ImportFrom` (`from tools.x import ...`, `from tools import ...`).
- Retains legal same-domain imports and external third-party/stdlib imports (`httpx`, `pydantic`, `os`).
- Tests: `tests/linters/test_domain_isolation_linter.py`.
