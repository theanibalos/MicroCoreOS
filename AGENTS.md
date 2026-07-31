# MicroCoreOS — AI Agent & Architecture Guide

This file is the single, absolute entry point for any AI agent (Gemini, Claude, GPT, etc.) working in this codebase. All development must strictly adhere to these principles to maintain the integrity of the Elastic Monolith.

---

## 🚦 Start here: `microcoreos status`

One command, before anything else. It answers the three questions that
silently derail a session: **which plan is actually active** (and whether it is
still the shipped template), **how much of it is done**, and **whether
`AI_CONTEXT.md` still describes the code on disk**.

There is exactly one plan path: **`plans/active_plan.yaml`**. The workflows,
the executor prompts and the checklist cross-check read that path and no other.
A plan written to `plans/my_feature.yaml` is a plan nothing will ever execute —
and because the shipped template is itself a valid plan, an agent that opens
`active_plan.yaml` and finds it untouched will build the *example* domain and
report success. That is why the template carries `template: true` and fails
validation until you delete the line.

---

## 📖 Your reading route — find your role, read those files, stop

Four roles do the work, and **each needs a different slice**. Reading outside
your slice is not thoroughness, it is budget: the Planner that also loads the
plugin templates spends ~3,000 tokens on code it will never write.

| You are… | Read exactly this | **Write exactly this** | Not this |
|---|---|---|---|
| **Planner** — turning a request into a plan | **1.** `plans/active_plan.yaml` — the file you are about to overwrite. It ships as a worked example of all three feature shapes, and it is the cheapest, densest statement of the format there is. **2.** `AI_CONTEXT.md` **down to `## 🧩 Plugin Authoring Guide`** (existing tools, tables, models, routes, events). **3.** `docs/PARALLEL_DEVELOPMENT.md` **§ Phase 1** for the rules behind it | **`plans/active_plan.yaml` + `plans/active_plan.md`, overwriting them.** Never a new filename — `plans/twitter_plan.yaml` is a plan nothing will execute | The Authoring Guide, Phases 2-3, `domains/`, `tools/`, `tests/`, `extras/` |
| **Phase 0 Builder** — migrations, models, tools | `plans/active_plan.yaml` **§ phase_0** only | Exactly the files `phase_0` names: its migrations, its models, its tools | Everything else. The plan already decided every column |
| **Executor** — one plugin + its test | **Nothing.** Your prompt already contains `AI_CONTEXT.md` + the plan + your one task line | Exactly two files: the `file:` and `test:` your task declares | Any file at all — opening one only invites guessed paths |
| **Coordinator** — dispatch, verify, reconstruct | `plans/active_plan.md` (the checklist/state machine) + `docs/PARALLEL_DEVELOPMENT.md` **§ Phases 2-3** | Only the checkboxes in `plans/active_plan.md` | The plan's internals; the checklist is the state |

If you are the Planner, the first thing you write is `plans/active_plan.yaml`
itself — not a draft under another name that someone copies later. The copy
step is where the plan gets lost: a validated plan sat in `plans/twitter_plan.yaml`
while two sessions in a row built the template's example domain instead.

And write it **before you ask anything**. Planning is usually a conversation,
and checking in is welcome — but never *instead of* writing. A plan that ends
as prose in your reply and a *"shall I proceed?"* produced nothing: the next
phase reads files, not answers, and the session may not be interactive at all.
Write the YAML, run `microcoreos plan validate`, and then ask — the operator
reviews a real file rather than a description of one.

**And the commands your role may run — nothing else boots the system:**

| Role | May run |
|---|---|
| Planner | `microcoreos status`, `microcoreos plan validate` |
| Phase 0 Builder | `microcoreos migrate`, `microcoreos schema` |
| Executor | none — write your two files and stop |
| Coordinator | `uv run -m pytest`, `microcoreos status`, and `microcoreos` (the real boot) for the final lint |

**Never `microcoreos run` / `uv run main.py` outside that last row.** It serves
forever: in the foreground it hangs your session, in the background it leaves a
process holding the port that makes the next `microcoreos migrate` refuse to
run. `migrate` is the boot that ends; `status` and `schema` answer everything
you would have booted to find out.

**No `AI_CONTEXT.md` in the project?** It is generated, not shipped — a freshly
scaffolded project has none until something boots. Run `microcoreos migrate`
once and it appears. Do not go exploring `domains/` and `tools/` to reconstruct
what it would have said: that is the search the manifest exists to replace, and
it costs an order of magnitude more to arrive at less.

Read on demand, never up front: `INSTRUCTIONS_FOR_AI.md` (building tools,
testing in depth, kernel internals) · `docs/TECH_DEBT.md` (only when scoping
work that may overlap an open item) · `domains/{domain}/models/{name}.py` (its
fields are already in `AI_CONTEXT.md`).

**Size the plan to the request** — over-planning a small one is a failure mode.
Every workflow below opens with the **same** two-file route as the Planner row
above, so following the ladder and following the table land in the same place;
each then adds only what is specific to its size. The phases themselves are in
`docs/PARALLEL_DEVELOPMENT.md` and are not repeated in any of them.

| Request | Workflow | Expected plan size |
|---|---|---|
| Plugin(s) on an EXISTING domain | `.agent/workflows/feature-plan.md` | Mini-plan, ~10-15 YAML lines per plugin, no `phase_0` |
| ONE new domain (e.g. a few CRUDs) | `.agent/workflows/new-domain.md` | ~80-120 YAML lines, one pass |
| Several domains / cross-domain event chains | `.agent/workflows/multi-domain-plan.md` | Full formal plan |
| New infrastructure tool (or replacement) | `.agent/workflows/new-tool.md` | No YAML plan — contract header + parity suite |

Omit every plan section that would be empty: no new tables → no `phase_0`;
no events → no `flows`. A CRUD-only plan has `features:` and nothing else.

---

## 💻 Commands

```bash
uv run main.py                                          # Run the app (also regenerates AI_CONTEXT.md)
microcoreos                                              # Same, if you installed the package (or: microcoreos run)
uv run -m pytest                                        # Run all tests (always -m: the pytest binary is not exposed)
uv run -m pytest tests/test_file.py                     # Run a single test
docker compose -f dev_infra/docker-compose.yml up -d    # Start dev infrastructure (PostgreSQL)
```

The plan pipeline — prefix with `uv run` if the package is installed in a venv:

```bash
microcoreos status                  # Active plan, progress, manifest freshness
microcoreos plan validate           # The 18 plan rules, OFFLINE (no server, no jq, no curl)
microcoreos migrate                 # Apply migrations AND regenerate AI_CONTEXT.md
microcoreos schema                  # The live tables and columns, read by the db tool itself
```

`microcoreos schema` is how you verify a migration. Do not reach for `sqlite3`
(not installed) or `import aiosqlite` from the system interpreter (it lives in
`.venv`) — and do not read the DB file directly: `describe_schema()` normalizes
types to the closed vocabulary every engine shares, so it reports what a swap
must preserve.

---

## 🛡️ Non-Negotiable Rules

1. **Never modify `main.py`** — The Kernel auto-discovers everything.
2. **1 file = 1 feature** — Each plugin lives in `domains/{domain}/plugins/{feature}_plugin.py`.
3. **No Framework Abstractions** — No Routers, Controllers, or Services. Only Tools (infrastructure) and Plugins (business logic).
4. **DI by parameter name** — `__init__(self, http, db, logger)` injects tools named `http`, `db`, `logger`. No hardcoded imports.
5. **Schemas inline** — Request, response, and event payload schemas go at the top of the plugin file, never in `models/`.
6. **No cross-domain imports** — Domains communicate ONLY through the `event_bus`.
7. **Return envelope** — `{"success": bool, "data": ..., "error": ...}`: `success` always present, `data` on success, `error` on failure. Responses serialize **as-is** — `response_model` does NOT backfill omitted keys, so an omitted key is absent from the JSON and consumers must never assume it exists.
8. **SQL Placeholders & Verbatim Migrations** — Always `$1, $2, $3...` (PostgreSQL style; SQLite converts internally). Migration SQL runs **verbatim** on the active engine (no dialect translation). Engine-specific SQL is a valid choice — it commits you to that engine; portable SQL (e.g. `CURRENT_TIMESTAMP`, not `NOW()`) keeps the SQLite↔PostgreSQL swap free. Either way, the swap includes a review pass (ELASTIC_DEPLOYMENT.md, Stage 1).
9. **Event Envelope Contract** — Subscribers receive `EventEnvelope` objects, not raw dicts. Access payload data via `event.payload`.
10. **Typed Event Payloads** — Define `XxxPayload(BaseModel)` in the PUBLISHER plugin and publish using `XxxPayload(...).model_dump()` (bare call, no args). Consumers must never import it; they declare their own model with only the fields they read (tolerant reader).
11. **Protected Endpoints**: Pass `auth_validator=self.auth.validate_token` to `add_endpoint` for non-public routes. Check ownership via `data["_auth"]["sub"]` inside the handler. **Why a callback and not an import:** plugins compose tools; tools never compose each other. `http` never imports `auth` — the plugin hands it a function, and that is the whole reason auth could become an extra without touching a line of the HTTP tool. The same rule produces `DurableOneShotsPlugin`, which composes `db + scheduler + event_bus` in the plugin layer to give the scheduler durability its tool cannot have alone.
12. **CSRF Guard & Cookie Security**: HTTP mutations (POST/PUT/DELETE) using cookie auth require the `X-Requested-With` header. Cookies set via `context.set_cookie` default to `Secure=True`, `HttpOnly=True`, `SameSite=Lax`.
13. **Core uses `print()`, not the logger** — Core modules must not depend on the logging tool.

---

## ⚖️ Core Architectural Laws

### The "No Hidden Magic" Rule (Kernel Level)
The Kernel (ToolProxy & Container) is infrastructure-blind:
1. **NO Kernel Retries**: `ToolProxy` is forbidden from automatically retrying failed tool calls. Automatic, blind retries at the kernel level lead to non-idempotent operation duplicates (e.g., double payments, duplicate database records).
2. **Explicit Resilience**: Resilience and idempotency are handled at the Tool level (connection pooling/locks) or Plugin level (business logic retry/compensation).
3. **Reactive Health**: `ToolProxy` marks tools as `DEAD` reactively (immediately if `ToolUnavailableError` is raised, or after 5 consecutive failures). Success resets the status to `OK`.

### Event Bus Mandates
1. **Universal Envelope**: All messages travel inside `EventEnvelope` objects. Emitters publish standard dicts; subscribers receive the full envelope.
2. **Decoupled Publication**: `publish()` is strictly fire-and-forget. Emitters must never know who consumes the event or when.
3. **Idempotency by Design**: Since durable transports re-deliver events after a crash (at-least-once), all event subscribers must be designed as idempotent.

### Security & Integrity
1. **Safe Error Reporting**: Never return raw exception strings (`str(e)`) to the client to prevent leak of paths, SQL structure, or keys. Log technical errors internally; return generic messages ("Database error") to the external client.
2. **Stateless JWT Logout**: By default, logout clears the cookie. JWTs remain valid until expiration. For critical revocation, use the `state` tool as a denylist.

---

## 🔄 The pipeline, in five lines

The methodology, the phase numbering and the executor-prompt mechanics live in
`docs/PARALLEL_DEVELOPMENT.md` — **canonically, and only there**. This used to
be a second copy of it, which is precisely how the copy drifted: it prescribed
`--boot-tool db` for phase 0 long after that stopped regenerating the manifest,
and no one compares two documents to notice.

| Phase | Command | Gate |
|---|---|---|
| 1 — Plan | *(the Planner writes `plans/active_plan.yaml` + `.md`)* | `microcoreos plan validate` → **zero errors** |
| 0 — Foundation | *(migrations + models, 1:1 from `phase_0`)* | `microcoreos migrate` then `microcoreos schema` |
| 2 — Wave | *(N executors, one plugin + one test each)* | every declared file exists |
| 3 — Verify | `uv run -m pytest` | green, then `GET /system/lint` clean |
| — Reconstruct | delete the failures, respawn fresh executors | all `[x]` in `plans/active_plan.md` |

Two rules the phases do not state on their own:

- **An invalid plan is fixed in the plan, never patched in code.** Errors carry
  the YAML that fixes them — paste it, do not re-derive it.
- **A plan is only ever `plans/active_plan.yaml`.** Any other filename is a plan
  nothing will execute, and the shipped template is itself valid, so nothing but
  its `template: true` marker can tell it apart from yours.

---

## 🔎 Where to Find Examples

When writing a new feature, read these specific files under demand to copy their syntax:

| Pattern | File |
|---|---|
| **CRUD + Event Bus** | `extras/available_domains/users/plugins/create_user_plugin.py` |
| **Protected Endpoint (JWT)** | `extras/available_domains/users/plugins/get_me_plugin.py` |
| **Auth, Cookies & Session** | `extras/available_domains/users/plugins/login_plugin.py` |
| **Minimal Plugin (No DB)** | `extras/available_domains/ping/plugins/ping_plugin.py` |
| **Database Migrations** | `extras/available_domains/users/migrations/001_create_users.sql` |
| **Dynamic Introspection** | `domains/system/plugins/system_status_plugin.py` |
| **Black-Box Integration Tests** | `tests/domains/users/test_login_plugin.py` |

Both point into `extras/` because both are extras: readable in any project,
and `microcoreos add auth` / `add ping` is what moves them into `domains/`.
Reading them needs no install — the files are there either way.

---

## 🔧 Common Infrastructure Operations

When tasked with infrastructure changes, read the specific guide in `docs/ELASTIC_DEPLOYMENT.md`:

| Operation | Guide Section |
|---|---|
| **Swap SQLite to PostgreSQL** | [ELASTIC_DEPLOYMENT.md (Stage 1)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L25-L90) |
| **Swap In-Memory State to Redis** | [ELASTIC_DEPLOYMENT.md (Section 2.1)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L98-L116) |
| **Scale Event Bus to Redis Streams** | [ELASTIC_DEPLOYMENT.md (Section 2.2)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L117-L141) |
| **Disable/Configure Scheduler on Replicas** | [ELASTIC_DEPLOYMENT.md (Section 2.3)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L142-L160) |
| **Production DB Migrations Pipeline** | [ELASTIC_DEPLOYMENT.md (Section 2.4)](file:///home/anibalos/Documents/Original/MicroCoreOS/docs/ELASTIC_DEPLOYMENT.md#L161-L177) |

