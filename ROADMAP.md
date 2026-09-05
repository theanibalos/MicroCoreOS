# Roadmap

> Active work, proposals and deferred subscopes only. Development tooling
> belongs to the harness/dev package; runtime tools remain general-purpose.
> Completed decisions and historical implementation notes live in
> [ROADMAP_DONE.md](ROADMAP_DONE.md). Issue IDs are stable across both files.
>
> Review scope: every entry read; active claims cross-checked against source,
> CLI, scaffold and CI. Historical tests/benchmarks are recorded evidence, not
> results rerun by this documentation review. Partial delivery is not closure.

## Review index

| Area | Status / next work |
|---|---|
| Core lifecycle | Issue 49 shipped (see ROADMAP_DONE.md) |
| Harness/devtools | Optional event types 47, unified check report 53; import gap 46 & signatures 50 shipped (see ROADMAP_DONE.md); remaining scopes 14/37/38 |
| HTTP tool | Issues 48 & 51 shipped (see ROADMAP_DONE.md) |
| Distribution | Packaged tools 44, demo 43, test distribution 42 (partial), marketplace 40 (deferred) |
| Event infrastructure | TLS/auth 45; ACL 16 and runtime contracts 23 still unimplemented |
| Integrity | Outbox 28 requires a confirmed transport handoff first |
| Exploratory | Starlette 10, event locality 24, driver optimizations 36, payload encryption 52 |

The maintainer roadmap is not an executable application plan. Application
features still use `plans/active_plan.yaml`; infrastructure changes use their
contract headers and parity suites. Nothing below silently activates runtime policy.

---

## 🧰 Development tooling / harness — proposed

These checks help agents and application developers; they are NOT kernel or
business features. Keep their analyzers offline in the devtools/dev-package
migration (docs/internal/DEV_PACKAGE_SPLIT.md). The framework CI tests the
checkers; applications choose their own CI provider and blocking policy.

**Issue 47 — 🟡 Optional, conservative event type compatibility**

Extend event analysis without requiring every event to have a fixed schema.
Publisher and consumer models remain independent tolerant-reader contracts.
Check directionally whether declared publisher values fit what a consumer
reads, not whether their models are identical. Extra publisher fields are fine
when the reader tolerates them; unions remain supported.

Start with a documented subset of JSON-compatible scalar types, nullability,
unions and required fields. Report compatible / potentially incompatible /
unverifiable; custom validators, coercions, dynamic payloads and unsupported
schemas are unverifiable, never guessed. Compare declared wire representations,
not merely Python annotation names. No general JSON Schema inclusion solver.

Advisory by default; a project may promote selected findings to CI errors or
waive them with a reason. No payload rewriting or runtime publication rejection.
Tests: wider reader union accepted; narrower reader warned; extra publisher
fields tolerated; optional/null distinctions preserved; dynamic/custom paths
remain explicitly unverifiable. This is independent of Issue 23's runtime guard.

---

**Issue 53 — 🟡 Unified checker report, application-owned CI policy**

Continue the split in `docs/internal/DEV_PACKAGE_SPLIT.md`, but use the actual
current baseline: `microcoreos_dev` already exists in the same wheel; the old
plan's NOT STARTED / separate-distribution framing is historical, not the next
step. Linters still live in `domains/devtools`; move their analysis offline
without breaking runtime event-schema metadata.

One structured finding/report contract for CLI and optional runtime diagnostics.
Include checker execution/completeness status: a missing checker must not look
like an empty findings list. Today the endpoint gate reads arch/tool-doc/event
warnings; real-repo tests additionally cover naming, tables and field divergence.
Route collisions are not checked by that endpoint gate, and discovery findings
are not included in its response. Add end-to-end tests proving configured
violations really produce a failing exit code. Applications choose severities,
waivers and CI provider; framework CI tests the checker itself. No mandatory
GitHub Actions, HTTP server or authentication for application linting.

**Issue 37 — 🟡 Remaining scopes only (scope 2 shipped)**

Within-domain field-constraint comparison and reasoned waivers are complete;
see the historical Issue 37 in [ROADMAP_DONE.md](ROADMAP_DONE.md).
Still deferred: event-field constraint comparison across instances (coordinate
with 47/23), and opt-in cross-domain vocabulary constraints. Never equate a
shared field NAME with a shared business CONCEPT. Keep these pending scopes
visible here even though the original implementation is archived as complete.

---

**Issue 44 — 🟡 `tools/` is for YOUR tools (scoped 2026-07-28)**

The direction, in one rule: **the framework's tools live in the package and are
maintained here; `tools/` in a user's project holds only the ones they wrote or
ejected.** A project that uses nothing but what ships does not have a `tools/`
directory at all — it is `domains/`, `main.py`, `.env`, `pyproject.toml`.

That rule is worth more than the earlier draft of this issue, which proposed
hiding *some* tools (`registry`, `context_manager`, `telemetry`, `config`) and
materializing the rest. That version needed a case-by-case defence of why `db`
is yours and `registry` is not. This one needs no list.

**What it buys:**

- **First contact stops being 101 files.** Almost all of them are tools nobody
  opens (Issue 43). A project becomes what the user actually writes.
- **`upgrade` stops being needed for tools.** They ship with the package and
  move with it. The hardest feature in the codebase shrinks to what it is
  really for: domains, and anything deliberately ejected.
- **`add` stops moving folders.** Dependency plus an environment variable —
  which is already exactly how `EVENT_BUS_DRIVER=kafka` selects a transport.

**What does NOT change, and this is the point:** swappability. Write a tool
with `name = "db"` into your own `tools/` and it wins over the packaged one.
The REPLACEMENT STANDARD headers stay exactly as they are; only the origin of
the default implementation moves.

**The five things to design, none of them large but none skippable:**

1. **Precedence, stated and tested.** A tool in the project beats a packaged
   tool of the same name. Today "only one tool per name may be discovered" is a
   sentence in the README; it becomes load-bearing and needs a test.
2. **What `eject` is.** `microcoreos eject http` copies that one tool out as
   your source, records it in the manifest, and from then on `upgrade` treats
   it like any other vendored file.
3. **Reading without ejecting.** Today you learn the framework by opening
   `tools/sqlite/sqlite_tool.py`. Hidden, a human loses that; an AI does not,
   because `AI_CONTEXT.md` already carries every signature. Something like
   `microcoreos show db` may be enough.
4. **The linters must see packaged tools.** `DiscoveryNamingLinter` scans
   files; `ToolDocDriftLinter` introspects raw container instances. The former
   needs packaged source roots; the latter needs the selected instances to
   remain visible. Do not treat both as filesystem scanners.
5. **The README's central claim changes.** "Tools and domains are copied into
   your project — you own them" becomes "domains are yours; tools are the
   framework's until you eject one". Arguably a better story — it is the Rails
   and Django model with an escape hatch, instead of vendoring by default —
   but it is the front page and it is a promise already made in 0.1.0.

**Do not confuse this with walking back the thesis.** `scaffold.py` argues that
install-and-swap *is* file placement, and that stays true for the case it was
written for: your tools, your domains, your edits. What moves is only the
default implementation of infrastructure the user never asked to own.

---

**Issue 43 — 🟡 A fresh project has nothing to look at (scoped 2026-07-28)**

**Review:** auth-as-extra and the `uv run` onboarding corrections are delivered;
`--demo` is not exposed by the current CLI/scaffolder. Route/file counts below
are historical measurements, not current inventory. The general-purpose kernel
must not acquire a mandatory web/auth dependency to improve this demo.

Moving auth to an extra the same day 0.1.0 shipped cost the first impression,
and the cost is bigger than it looked. A newly scaffolded project now serves:

```
12 routes, every one of them /system/*
```

Observability endpoints and no business feature. Yesterday the same command
gave you `POST /users`, `POST /auth/login` and `GET /users/me` — a working CRUD
with JWT and CSRF, on the first boot, with nothing configured. TECH_DEBT item 1
recorded exactly this as the argument against ("a web framework whose default
project cannot log anyone in is a strange default"). It was foreseen, and it is
worse in practice than on paper.

**Do not fix it by reverting.** The architectural case stands: a webhook
receiver should not inherit a users table, a roles model, a JWT flavour and a
mandatory `AUTH_SECRET_KEY`. Two different questions got the same answer by
accident — *what should a default project contain* and *what should an
evaluator see in sixty seconds*. They can be answered separately.

**Why this is not a marketing item.** The comparison that matters is not
`@app.get("/")` — that is a library, and this is an architecture. It is
`full-stack-fastapi-template`: Docker, Traefik, Alembic, a React frontend,
hundreds of files people fork and never finish reading. Against that, 101 files
is modest, and the real claim is not "fewer files" but **the number of files
you must understand does not grow with the project** — two, `AI_CONTEXT.md` and
one plugin, no matter how large the codebase gets.

The demo is the only thing that *demonstrates* that in sixty seconds. Someone
who boots, sees `POST /users` in `/docs`, wonders where it lives and finds
`domains/users/plugins/create_user_plugin.py` — one file, schema and logic and
event together — has understood the whole thesis without being told. With
twelve `/system` routes there is nothing to trace. What is lost is the proof,
not the decoration.

**Three stumbles observed live, 2026-07-28, by the framework's own author**
following his own README on a clean machine. None of them is a code bug; all
three are onboarding text, and none produced a message that pointed anywhere
useful:

1. `uv add microcoreos new .` instead of `uv run`. The two lines of the Quick
   Start begin identically and do unrelated things. uv's error talks about
   self-dependencies and the project name — nothing about the wrong subcommand.
2. `uv add 'microcoreos[auth]'` and then a boot with no auth. That installs the
   **dependency only**; the source stays in `extras/` where nothing discovers
   it. **Nothing fails** — the system boots green with the feature simply
   absent, which is the worst possible feedback. The README listed `uv add` as
   the primary form and `microcoreos add` as "better still". Reversed now: the
   one-step command is the form, and the extra is described as the piece it
   installs.
3. `microcoreos add auth` → `command not found`, then `microcoreos add <extra>`
   → a bash syntax error from the angle brackets. The console script lives in
   `.venv/bin`. **The docs had 28 bare `microcoreos ...` invocations against 3
   with `uv run`** — including the NEXT_STEPS message `new` prints, which is
   the single highest-traffic text in the product and told every user to type a
   command that does not resolve.

Fixed in NEXT_STEPS, the README and `docs/CLI.md` (which now states the prefix
once, at the top, and that `<brackets>` are placeholders). The remaining bare
invocations across the docs are worth a sweep.

**Two moves, in order:**

1. **The Quick Start becomes two commands** (no code): `microcoreos new my-app`
   then `microcoreos add auth`. Whoever is evaluating sees what they used to;
   whoever does not want auth simply does not type it.
2. **`microcoreos new --demo`**: scaffold and install auth in one command, so
   the sixty-second path stays one line while `new` on its own keeps giving a
   clean project.

---

**Issue 42 — 🟡 Ship the tests with the code they test (PARTIALLY DELIVERED)**

**Current source check:** `scaffold.RUNTIME_ENTRIES` now ships `tests/helpers`,
and tool-local tests travel in extras. Generated pyproject configures pytest and
anyio when the scaffolder creates it. The full default-tool/system/linter suites
and root `conftest.py` are not all in the scaffold allowlist. Do not redo helper
shipping; scope the remaining fixture and suite distribution explicitly.

Original motivation: a scaffolded project got `pytest` configured and nothing
to run: no `tests/`, no `conftest.py`, no fixtures. Yet the testing model is documented as a
selling point — black-box plugins, fixtures named after the Kernel's injection
keys so a test's signature and its plugin's signature are the same vocabulary.
That `conftest.py` exists only in this repo, so anyone following the README has
to rebuild it from scratch without knowing it is there.

The principle is the vendoring one, already applied everywhere else: **if the
code is yours, its tests are yours.** You own `tools/sqlite/sqlite_tool.py` —
edit it and only its tests can tell you whether it still honours the contract.
`microcoreos upgrade` would carry test fixes the same way it carries tool
fixes.

The split mirrors the kernel/distribution line drawn in `microcoreos/`
(`tests/core/test_core_purity.py`):

- **Ships:** `conftest.py`, `tests/helpers/`, the tests of the nine default
  tools, the `devtools` linter tests and the `system` domain tests. Their
  imports (`from tools.sqlite...`) are already identical in this repo and in a
  user's project, so they travel unchanged.
- **Does not ship:** `test_kernel.py`, `test_core.py`, `test_tool_proxy.py`,
  `test_registry_collisions.py`, `test_cli.py`, `test_scaffold.py`,
  `test_catalog.py`, `test_upgrade.py`, `test_core_purity.py` — all of them
  test the package, which the user does not own and cannot edit.
- **Travels with its extra:** `add postgres` should also place
  `test_postgresql_tool.py`, `add auth` its plugin tests, and so on.

**Two things to solve before it can be done, both verified:**

1. **Extras tests import a path that moves.** They read
   `from extras.available_domains.users.plugins...`, but `microcoreos add auth`
   puts that code in `domains/users/`. Shipped as-is they would import
   something that does not exist there. `add` already moves folders and records
   the move in the manifest; rewriting that one import line while it moves is
   mechanical, but it is a design decision nobody has made.
2. **External-service tests need explicit modes.** Local optional suites should
   skip cleanly without a broker/DB; mandatory framework CI jobs must fail when
   their fixture is unavailable. The old count of fourteen files is historical,
   not remeasured here. The current PostgreSQL test path is
   `extras/available_tools/postgresql/tests/postgresql_tool_test.py`; do not
   restore `test_*_tool.py` names that discovery would import at boot.

**Suggested order.** Phase 1 is the fixtures plus the default-tool tests: no
obstacle, and it carries most of the value, since the common case is a user
editing a tool they were given. Phase 2 is the extras, and it needs decisions 1
and 2 first.

---

**Issue 14 — 🚀 Automatic Test Generation (1 Plugin = 1 Test)**

Every new plugin should come with its own unit test automatically generated by the LLM.

**Strategy:**
- **Sequential Generation**: First generate the plugin code, then the test code.
- **Contract-Aware Testing**: Generate against the feature spec; the same executor may read its own plugin, not another executor's implementation.
- **Black-Box Tests**: Use real local tools/fixtures where practical; mock the dependency whose failure is deliberately forced. Do not require mocks for every tool, which would hide SQL/API drift.
- **Harness Integration**: Optional runner/UI integration; no Studio product is assumed to exist in this repository. This issue belongs to development tooling, not runtime.

**Update 2026-07-11**: the plan formats now declare every test up front — one
`test:` per feature and one `e2e_test:` per flow (validity rules 5 & 8 in
`docs/PARALLEL_DEVELOPMENT.md`, chain helper in `tests/helpers/trace_chains.py`).
Generation now has an explicit spec to target instead of inferring what to test.

---

**Issue 38 — 🟡 API vocabulary consistency (PARTIALLY DELIVERED)**

**Review:** `language:` and rule 16 live in `microcoreos_dev/plan/schema.py` and
`rules.py`; they are implemented, as is manifest request/response extraction.
The storage-vocabulary drift checker and optional HTTP plan contracts remain
proposals. Older references to `PlanValidatorPlugin` below describe the design;
the validator now runs offline, with no plan-validation HTTP endpoint.

**The gap, stated exactly.** A `features:` entry declares `route: {method, path}`,
`db:`, `publishes.payload: {id: int, user_id: int}` — exact keys AND types for
every EVENT — but **nothing for the HTTP body**. There is no `request:` and no
`response:` key in the format. `docs/PARALLEL_DEVELOPMENT.md` line 200 states the
intent ("the plan pins down what a feature exposes: request in, response out")
and the YAML has no mechanism for it. So a wave executor receives
`POST /orders` plus a one-line `function:` and invents the field names itself.

**What is actually at risk — and what is NOT.** An executor inventing the *shape*
of the feature it owns is fine and deliberate: that is local design freedom, and
the black-box test proves it honors what it declared. The hazard is **vocabulary
divergence across plugins for the SAME data**: every plugin internally coherent,
every test green, and the API incoherent. The black-box test cannot see it —
it proves a feature honors ITS contract, never that two features name the same
thing the same way (same species as Issues 26/27/37).

**But most fields are already anchored, which is why this has never bitten.**
Two of the three places are pinned by the existing format: `db: {writes: [...]}`
forces the SQL to use the real column names, and `publishes.payload: {...}` /
`consumes.requires: [...]` pin the event keys exactly. Only the HTTP body is
free — and when a plugin must store `user_id` in the `user_id` column and
publish it as `user_id`, naming the request field anything else is extra work.
**The name propagates by gravity.** `user_id` vs `client_id` for the same column
is therefore a theoretical risk, not the real one.

**The real exposure is the UNANCHORED fields** — the ones with no column and no
payload key behind them, where nothing pulls the name into place:

- pagination: `limit`/`offset` vs `page`/`per_page` vs `take`/`skip`
- search & filters: `q` vs `query` vs `search`
- pure inputs that never reach a column under that name: `password`
  (stored as `password_hash`), `confirm`, `remember_me`
- response envelope extras: `total_count` vs `total` vs `count`, `has_more`
  vs `next_cursor`

This is why CRUD-plus-event-chain builds never surfaced it: nearly every field
there is anchored. It appears the first time several domains grow list
endpoints with pagination and filtering — the fields no contract mentions.

The cost lands later and hard — it is the API's public surface, so fixing it
after clients exist means a breaking change, unlike an internal duplication.

**Why phase 0 already almost solves it.** The instinct behind writing migrations
and models BEFORE any plugin was right: phase 0 is exactly where the shared
vocabulary is fixed, because **the column names ARE the vocabulary**. What is
missing is stating that they bind the API layer too.

Three options, cheapest first:

1. **House vocabulary for the unanchored fields (recommended, and the only one
   that targets the real exposure).** Anchored fields need no rule — gravity
   already handles them; writing one down (*an API field backed by a column
   carries the column's name*) costs a line in `AGENTS.md` and is worth having,
   but it is a backstop, not the fix. What actually needs deciding ONCE and
   living in `tools/context/authoring_guide.md` — which every executor receives
   embedded in the manifest — is the vocabulary nothing else pins:
   ```
   pagination: limit + offset       (never page/per_page, never take/skip)
   search:     q                    (never query, never search)
   envelope:   total, has_more      (never total_count, never count)
   ```
   Five lines, zero mechanism, and it reaches every executor in the wave through
   the prefix they already read. The linter for it (compare request/response
   field names across plugins, flag near-synonyms) is the same family as Issues
   26/27/37 and can wait for evidence; the column list it would need already
   exists via `db.describe_schema()` (2026-07-26).
2. **`request:` / `response:` in the plan (heavier, explicit).** Symmetric with
   `publishes.payload:`, including constraints — which is where divergence
   actually lives (`gt=0` vs `ge=0`):
   ```yaml
   route:    { method: POST, path: /orders }
   request:  { user_id: int, total: "float>0", note: "str(0..500)?" }
   response: { id: int, total: float }        # the contents of data{}
   ```
   Plus a validity rule: a feature with a `route` declares `response`; a
   POST/PUT/PATCH route declares `request`. This is plan format v4 — it touches
   `docs/PARALLEL_DEVELOPMENT.md`, `PlanValidatorPlugin` and the authoring guide.
   Correct, but it moves work back onto the planner for every feature, including
   the ones where invention is harmless.
3. **Both**, with (2) reserved for genuinely new shapes and (1) as the backstop.

**Manifest side — IMPLEMENTED for supported AST patterns.**
`tools/context/scanners.py::_get_domain_endpoints()` already extracts inline
request/response models and their fields; `ContextTool` renders them. Do not
schedule that work again. Dynamically assembled registrations remain outside
what this static extraction can prove. HTTP request/response declarations in
application plans remain a proposal, separate from this delivered capability.

Note the division of labour once both exist: the **table** section describes
STORAGE (write SQL from it), the **endpoint** section describes the API
(stay consistent with it), and the plan declares what the NEW feature exposes.
`users.roles` is `text` in storage and `list[str]` over the wire — both true,
both visible, neither derived from a hand-written mirror.

---

### The chosen answer: a `language:` section in the plan (design, 2026-07-26)

> **Status (2026-07-29): the section and its validity rules are IMPLEMENTED** —
> `language:` in the plan schema, enforced as rule 16 of `PlanValidatorPlugin`
> (name-equality against real columns, `breaking: true` mandatory on
> rename/remove). The **drift linter is NOT** — per the order of implementation
> below, it waits for the first model field found naming a column that no
> longer exists.

The entity model is the domain's **ubiquitous language** — not a mirror of the
table. Storage and vocabulary answer different questions and are allowed to
differ: `password_hash` is a column and must NEVER be a model field (it never
leaves the system), `roles` is `TEXT` on disk and `list[str]` in the domain.
Applied already to `domains/users/models/user.py` (2026-07-26), and the manifest
now publishes both lines per domain:

```
- **Table `users`** (storage): id (int, PK), …, password_hash (text, NOT NULL), roles (text, …)
- **Model `UserEntity`** (domain vocabulary): id: int | None, name: str, email: EmailStr, roles: list[str]
```

**Why it needs a plan section.** The vocabulary is a DECISION, not something
derivable from code — no introspection can know whether the business says
`client` or `customer`. `phase_0.models` covers only the plan that CREATES a
domain; the 4th plan adding three plugins to an existing domain has no `phase_0`
and therefore no way to amend the language. Today it would silently invent one.

**Shape.** Top-level `language:`, independent of `phase_0` so it works in any
plan. Omitted entirely when the plan does not touch the vocabulary — most
feature plans will not have it (Plan sizing rule).

```yaml
language:
  # NEW concept — the domain gains an entity
  - model: OrderEntity
    domain: orders
    op: new
    table: orders                       # the table that backs it
    fields: { id: "int?", user_id: int, total: float, status: str }
    internal: [payment_token]           # columns deliberately NOT in the language

  # CHANGE — additive, the common case
  - model: UserEntity
    domain: users
    op: add_field
    fields: { phone: "str?" }
    backed_by: users.phone              # must exist, or be declared in this plan's phase_0

  # RENAME — breaking, the dangerous case
  - model: OrderEntity
    domain: orders
    op: rename_field
    from: client_id
    to: user_id
    breaking: true                      # MANDATORY on rename/remove
    affects: [GET /orders, POST /orders]  # endpoints that speak the old name
    reason: "the domain says user, never client"

  # DELETE
  - model: UserEntity
    domain: users
    op: remove_field
    field: legacy_code
    breaking: true
    affects: [GET /users/{user_id}]
    reason: "dropped with the 2026-08 migration"
```

**What this buys that documentation alone does not:** `rename_field` and
`remove_field` are breaking changes to a public API, and today NOTHING makes
anyone notice. Requiring `breaking: true` plus `affects:` turns a silent rename
into an explicit act with a blast radius written down.

**New validity rules for `PlanValidatorPlugin`** (it already cross-checks routes,
tables and events against the live system; these ride the same call):

- Every `new` / `add_field` field must resolve to a real column — either present
  in `db.describe_schema()` (2026-07-26) or declared in this plan's
  `phase_0.migrations.columns`. A vocabulary field with nothing behind it is an
  error, not a style issue.
- A model field's name must equal its column's name (rule 10, one level up).
  Projections of TYPE are free (`text` → `list[str]`); projections of NAME are not.
- `rename_field` / `remove_field` without `breaking: true` → ERROR.
- `internal:` columns are the declared exceptions: they exist in storage and are
  deliberately absent from the language. This is what makes the drift linter
  possible without false positives — see below.

**And it settles the drift linter (the point 3 objection).** The check runs in
ONE direction only: *every model field must map to an existing column.* A column
with no model field is normal and expected — that is `password_hash`, and
`internal:` records that it is deliberate. So the linter can never flag
`password` vs `password_hash` as drift; the only thing it catches is the rare
real error, a model field naming a column that was renamed or dropped. Rides in
the devtools linters with Issues 26/27/37.

**Frequency check (why the hand-written model is cheap).** Domain vocabulary
changes are additive and decelerating: core entities settle in weeks, and
adding a field is the same edit as the migration that backs it, in the same
plan. Rename and remove — the expensive path this section guards — are rare
precisely because they break clients. And a model defined as VOCABULARY changes
less than one defined as a table mirror: storage churns for denormalization,
caching and type changes that never touch what the domain calls things.

**Order of implementation:** the `language:` section and its validity rules
first (they are what stop the problem at the source), the drift linter after —
it is the backstop for code written outside the plan workflow, exactly like
Issues 26/27 are backstops for plan rules 1 and 2/14.

**Trigger:** the section is worth writing now — it is format, not code, and the
4th-plan gap is real today. The linter waits for the same evidence every other
linter here waited for: the first model field found naming a column that no
longer exists.

---

**Issue 10 — 🔬 Migrate HttpServerTool from FastAPI to pure Starlette (exploratory)**

FastAPI is already a thin wrapper over Starlette. Most imports in `http_server_tool.py` are Starlette classes re-exported by FastAPI (`Request`, `WebSocket`, `JSONResponse`, `StreamingResponse`, `StaticFiles`, `CORSMiddleware`, `run_in_threadpool`). What is exclusively FastAPI is minimal: the app object, `Depends()` for GET query params, `response_model`/`tags` in `add_api_route`, and the auto-generated docs at `/docs`.

---

**Issue 40 — 🟡 Drop-in marketplace for tools and domains (deferred until one exists)**

WordPress plugins land in `wp-content/plugins/`, VS Code extensions in the
user's extensions dir — both are "drop a directory in, it is discovered". The
Kernel already works exactly that way, and Issue 39's materialization model is
the same mechanism, so the marketplace needs no new architecture. What it needs
is the surrounding machinery, and one bug fixed first.

**Design prerequisite — tool name collisions are silent.** `microcoreos/container.py` does
`self._tools[tool.name] = ToolProxy(...)` with no existence check. Two tools
claiming `"state"` and the second silently replaces the first; `list_tools()`
reports one. Worse, *which* one wins depends on registration order, which comes
from the `asyncio.gather` in `_setup_tool` — the same non-determinism already
visible in the tool ordering of a regenerated `AI_CONTEXT.md`. Today this is
survivable because README tells you to move the replaced tool out of `tools/`
first, by hand. With third parties publishing, a coin flip per boot is not
survivable. `tests/core/test_registry_collisions.py` covers the PLUGIN case (solved
by the domain prefix). Choose an explicit duplicate policy together with Issue
44 (checker rejection or declared replacement). Duplicate names are programmer
configuration errors, not evidence of hostile plugins; no kernel change is
approved solely by this marketplace proposal.

**Already in place — the acceptance gate.** The hardest part of a marketplace
is answering "does this stranger's tool really honour the contract?", and the
answer is already executable: `tests/tools/db/test_db_parity.py`,
`test_state_parity.py`, `test_event_bus_broker_parity.py`, `test_s3_parity.py`.
A tool published as `db` must pass the db parity suite. Written for Issue 22,
reusable as-is.

**Already delivered:** `microcoreos add` installs the bundled extras through
`microcoreos/catalog.py`; this is not a third-party marketplace client.
**Still missing:** a third-party catalog/manifest (name, version, author,
contract and env settings) and a trust story, since
drop-in code runs at boot with full access — the security history of WordPress
plugins is the cautionary tale. Worth deciding before third parties publish,
not before.

---

## 🌐 Distributed Track — active

**Issue 45 — 🟡 Optional broker TLS and authentication (PROPOSED — not implemented)**

Infrastructure plan, not an application feature plan (`new-tool.md`): no new
business plugins, no migrations, no kernel changes, no change to the public
Bus API. The operator chooses transport security; plugins remain unchanged.

### Contract to approve before implementation

- TLS applies to a CLIENT CONNECTION, not individual events. An instance's
  broker connections use one explicit policy. Topic/stream/queue permissions
  are broker ACLs, separate from TLS and from Issue 16's event ownership.
- Preserve current local-development behavior: TLS off unless enabled.
  Production guidance recommends TLS plus authenticated, least-privilege
  broker identities. No automatic plaintext fallback, including reconnects.
- Proposed switches: `REDIS_TLS_ENABLED`, `RABBITMQ_TLS_ENABLED`,
  `KAFKA_TLS_ENABLED` (strict true/false). Redis state and Redis Streams honor
  the same Redis settings. SQLite and in-process transport are unaffected.
- Each prefix also accepts `TLS_CA_FILE`, `TLS_CERT_FILE`, `TLS_KEY_FILE`.
  TLS enabled uses certificate AND hostname verification, minimum TLS 1.2.
  An omitted CA file means the OS trust store, NOT disabled verification.
  Client certificate/key must appear together; both are optional unless the
  broker requires mutual TLS. Never generate an insecure SSL context.
- TLS options supplied while TLS is off, invalid boolean values, missing files,
  invalid certificate/key pairs, or incompatible auth configuration fail setup
  explicitly. No silently ignored security settings. A TLS-enabled connection
  must complete verified TLS before setup succeeds; certificate, hostname or
  handshake errors leave that tool unavailable, never registered as ready.
  This does NOT require the whole general-purpose application to terminate:
  the existing kernel records setup failure and skips dependent plugins.
- Authentication is independent of TLS: Redis gets `REDIS_USERNAME` plus its
  existing password; RabbitMQ keeps user/password/vhost; Kafka gets explicit
  SASL mechanism and credentials. Initial Kafka scope: PLAIN and SCRAM-SHA-256/
  SCRAM-SHA-512; OAuth/GSSAPI deferred. Derive Kafka security_protocol from TLS
  and SASL settings, rather than accepting contradictory selectors. Reject
  incomplete credentials; document that plaintext auth exposes credentials.
- Broker ACLs are provisioned OUTSIDE the framework. Document minimum rights
  for ordinary delivery, consumer groups, RPC replies and delayed delivery;
  Kafka currently creates topics, so disclose its admin permissions rather
  than claiming publish/consume-only access. Do not log passwords or keys.

### Implementation sequence and file scope

1. **Pin contract and configuration tests** in the affected tool/driver headers
   and tool-local tests (`*_test.py`, never discovery-compatible test names).
   Preserve existing API/parity expectations; reject invalid config offline.
2. **Redis:** `tools/event_bus/redis_streams_driver.py` and
   `extras/available_tools/redis_state/redis_state_tool.py`. Separate clients,
   same settings; no tool-to-tool dependency. Test both implementations.
3. **RabbitMQ:** `extras/available_tools/rabbitmq/rabbitmq_driver.py`.
   Verified SSLContext and optional client certificates, also on reconnect.
4. **Kafka:** `extras/available_tools/kafka/kafka_driver.py`. One private
   connection-options builder used by admin, producer, ordinary consumers,
   reply consumers and delay scheduler. No connection may bypass the policy.
5. **Distribution/docs:** `microcoreos/catalog.py`, `.env.example`, driver
   interface descriptions and `docs/ELASTIC_DEPLOYMENT.md`. Keep TLS opt-in;
   describe secure deployment without imposing user authentication on the app.
6. **Framework verification:** isolated TLS broker fixtures under `dev_infra/`
   and integration jobs in `.github/workflows/ci.yml`. This is the framework's
   assurance suite, not a mandated CI provider for applications using it.

### Acceptance gates

- Existing plaintext parity suites still pass, including Redis state.
- Secure publish/consume, groups, RPC and delayed delivery pass against real
  TLS brokers with trusted certificates and correct credentials.
- Unknown CA, wrong hostname, expired certificate, missing client certificate
  when mTLS is required, wrong credentials and broker-down all fail setup.
- Reconnect never downgrades. A plaintext-only broker cannot satisfy TLS mode.
- A broker ACL denying publication produces a transport rejection, never a
  fabricated receipt. Assert at the driver boundary: the current public
  `publish()` is fire-and-forget and does not surface broker rejection to its
  caller. A confirmed publish contract belongs to Issue 28's prerequisite,
  not to this TLS change.
- Mandatory secure CI jobs fail if their broker fixture is unavailable; they
  must not pass by skipping all integration tests. Ordinary developer runs
  may still skip optional external-service suites.

**Open decisions:** approve proposed env names, whether plaintext credentials
should warn or require an explicit extra opt-in, and broker permission recipes
for deployments that pre-provision topology. TLS does not promise disk
persistence, event authorization or exactly-once processing.

---

**Issue 16 — 🌐 Event ACL enforcement (trimmed 2026-07-11)**

*The driver work originally listed here lives in Issue 18 (Redis Streams
already proved zero-code scaling: a domain moves to a separate instance by
copying its folder). What remains of this issue is ACL only.*

The `billing` domain should be the only one authorized to publish
`invoice.paid`. Current bus behavior attributes the emitter from ContextVars
and discards manual emitter overrides; it does NOT authorize event names.

First scope to design: optional devtools ownership checks against approved
publisher declarations. Runtime bus enforcement remains a separate opt-in
proposal, not implemented. Persist ownership across plans: the active plan is
incremental work, not the fleet's permanent authorization database. Publisher
metadata exists behind the schema catalog; the public JSON Schemas alone are
not an authorization policy.

Plugins within one process are trusted application code. ContextVars are
attribution, not an adversarial isolation boundary. Broker ACLs distinguish
service credentials, not Python domains sharing one connection. Protected
review/CI and broker identities are separate deployment controls.

---

**Issue 23 — 🟡 Runtime event contracts (Dynamic Event Guard) — simplified 2026-07-11**

The `EventContractLinterPlugin` is static analysis of local code: if the
consumer lives in ANOTHER instance, it cannot see it. The path is now concrete
thanks to typed payloads:

1. Each instance serves its own contract catalog (`/system/events/schemas`).
   The **union of the fleet's catalogs IS the system contract** — mechanically
   comparable across instances, no remote static analysis needed.
2. Schema Registry integration is NOT implemented: the Kafka driver currently
   serializes JSON and has no registry-backed serializer. A registry alone does
   not make an ordinary Kafka broker validate payloads. Design explicit producer
   validation/serialization (or a supported broker-side enforcement product)
   before claiming runtime enforcement. The local schema catalog is input to
   that integration, not proof it exists.

---

**Issue 24 — 🟡 Distributed observability — decided 2026-07-11: export local, aggregate outside**

**Each replica exports what it sees; an external platform aggregates the
fleet. No custom aggregator gets built here** (same discipline as Issue 13:
don't rebuild what the platform layer already solves). By signal:

- **Causal tree**: in distributed mode every event transits the shared broker,
  so fleet-wide causality is read at the broker itself — an external consumer
  over the topics/streams (since the 2026-07-19 wildcard removal, Issue 36,
  this is broker tooling, not a Bus subscription). Verified: envelopes carry
  `id`/`parent_id` across instances intact.
- **Spans & tool metrics**: genuinely per-process → OTel (already integrated)
  exports per replica; Jaeger/Tempo/Prometheus aggregate. Building our own
  aggregator would be rebuilding Tempo.
- **Health & lint** (`/system/status`, `/system/lint`): per replica, correct
  as-is — the orchestrator/load balancer that already watches each replica is
  the aggregator.
- Exploratory (kept): **event locality** — deliver an event in the local
  instance without a broker round-trip when the consumer lives there.

**Review:** export-local/aggregate-outside is a settled architecture decision,
not an unfinished aggregator. Event locality and any deployment-specific exporter
integration remain exploratory; no new aggregator implementation is planned.

---

**Issue 28 — 🟡 Transactional Outbox (deferred by decision, 2026-07-11)**

Deliberately NOT implemented yet — same criterion as Issue 13 (rate limiting):
a pattern is specified now; code ships only when a real feature demands it.

**The problem it solves — atomicity, not durability.** Today a plugin commits
its business INSERT and then publishes; if the process dies between the two,
the event is lost. This gap is NOT covered by a distributed broker: Kafka's
log protects the event from the broker onwards, and offsets/consumer-groups
protect the consumer side — nothing protects the segment between the business
DB commit and the publish reaching the broker. For the same reason the outbox
can never live inside the event bus (a bus with its own storage is a dual
write again, and that storage is exactly what Kafka already provides). The
outbox row must be written **in the same business-DB transaction** as the
business data — so it lives where that transaction is visible: the plugin layer.

**Design (follows the Issue 19 precedent — a tool never uses other tools;
compose in the plugin layer):**
- Optional outbox bundle, not a mandatory `system` migration: table
  `event_outbox` (stable id, event, payload, causality metadata, created_at,
  published_at NULL; lease fields if multiple relays are supported).
- The pattern: the business plugin writes its INSERT **and** the outbox INSERT
  inside the same `db.transaction()` block.
- **Prerequisite:** design an opt-in confirmed transport handoff. Current
  `await bus.publish()` returns before the driver completes; it cannot justify
  marking an outbox row sent. Preserve fire-and-forget for existing callers;
  any new API follows the contract-freeze admission rule (historical Issue 36).
  Confirmed means transport acceptance under documented durability settings,
  NEVER consumer completion. Redis XADD alone does not prove fsync/replication.
- `OutboxRelayPlugin`: scheduler cron reads pending rows, claims a bounded lease
  where needed, awaits confirmed transport handoff, then marks `published_at`.
  Error/timeout remains retryable; timeout may mean unknown acceptance. Crash
  after acceptance but before marking causes duplicates, so retain stable event
  IDs and require durable consumer idempotency. No kernel retries.
  **Note (2026-07-27):** it depends on the `scheduler` tool, which is now an
  extra (Issue 39). So it cannot live in `domains/system` — a mandatory plugin
  cannot depend on an optional tool. It belongs either in the scheduler
  domain's bundle (`extras/available_domains/scheduler/`) or in a bundle of
  its own; its migration travels with it, not with `system`.
- Transport-agnostic by construction: swapping the bus driver to Kafka changes
  nothing in the relay — the outbox is what makes that swap safe for
  features that need it.

**Implementation trigger:** the first real feature whose event chain answers
"no" to the plan checklist question *"can this chain tolerate losing the event
if the process dies between commit and publish?"* (payments, orders, billing).
The formal plan format carries that checkbox per chain (`atomic_with_db`).

**Consumer completion:** in the consumer's SAME business DB transaction,
insert a unique `(consumer, event_id)` inbox/dedupe record, apply the business
write, and insert an outbox result event. Its relay publishes completion later.
Duplicate deliveries must not repeat the write or result insertion. External
provider calls are outside that DB transaction and need their own idempotency.

**Design trade-offs (not universal limitations of outbox):**
- **Causality is preservable.** Store the original parent/correlation metadata
  with the row and restore it at relay publication through the approved API.
  A relay publishing only in its cron context loses the causal edge, but that
  is an implementation choice, not an unavoidable price of atomicity.
- **Polling adds latency.** A one-batch-per-tick relay may take one poll per
  chain hop; bounded drain loops can process more per tick. Expose pending
  count/oldest age through infrastructure diagnostics without requiring HTTP.
- **Atomicity on the publish side doesn't imply atomicity on the consume
  side.** `atomic_with_db` only protects the commit→publish segment;
  `idempotent: true` on the receiving link is a separate, unenforced claim.
  If the dedupe check behind it lives in process memory (not a persisted
  read/write against a table), a restart resets it exactly like a
  non-atomic publish would lose an event — the same durability requirement
  that motivates the outbox applies symmetrically to the consumer's own
  idempotency check.

**Acceptance before shipping:** commit/rollback atomicity, consumer duplicate
handling, restart recovery, relay lease expiry, broker rejection, unknown
handoff timeout, crash after broker acceptance, and causality preservation.
Choosing a durable driver alone is NOT the install trigger: the business needs
commit-to-event atomicity. This extra has not been implemented by this review.

---

**Issue 36 — 🟡 Deferred subscopes only (Bus contract freeze is settled)**

The admission rule and wildcard-removal history live in
[ROADMAP_DONE.md](ROADMAP_DONE.md). Keep its unimplemented options visible:
- Kafka delay buckets: only when mixed delays cause measured head-of-line delay.
- Multiplexed Kafka RPC reply consumers: only when RPC is a measured hot path.
- Plugin-layer idempotency helper: only when a real consumer needs one;
  durable flows require persistent deduplication, not process-memory state.
None authorizes a public Bus API change without the existing admission gate.

**Issue 52 — 🔬 Event confidentiality requirements / payload encryption**

Exploratory, separate from the scoped TLS implementation in Issue 45.
A future event contract may REQUIRE encrypted remote transport; it must not
require plaintext for public events. One TLS connection can carry both kinds.
Start with optional deployment checks against declared transport properties;
define how in-process/local transports satisfy or make the requirement
inapplicable. Never silently downgrade a security requirement as a best-effort
hint. Runtime enforcement, if needed, requires a separate Bus contract decision.

TLS belongs in drivers and protects client-to-broker traffic. End-to-end payload
encryption protects content FROM the broker and is not automatically provided
by TLS. Do not duplicate cryptography in each broker driver: first define a
broker-neutral authenticated-encryption format, key IDs/rotation and recipient
access, using vetted libraries and a key-management design. Placement remains
open (explicit plugin composition or an approved transport codec seam); tools
must not start depending on other tools implicitly.

Before implementation, resolve schema validation timing, retry/DLQ behavior,
RPC replies, metadata leakage and local trace/listener exposure. Current Bus
listeners see plaintext before driver publication: driver-only encryption
would NOT protect those sinks. No cipher/key storage/API is selected yet;
require a concrete confidentiality threat model and parity/failure tests.
