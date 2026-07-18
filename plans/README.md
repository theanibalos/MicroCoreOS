# Human Operator Guide: Multi-Agent Planning & Execution

This guide gives you (the Human Operator) a copy-paste prompt or command for
**every interaction with an AI** in the workflow. The core philosophy: **all
design decisions, data schemas, and event flows are defined in the plan
first**. Executors only write code that satisfies the plan's contract.

## Roles — which AI does what

| Role | Intelligence tier | Reads | Writes |
|---|---|---|---|
| **Planner** | The smartest model you have | `AI_CONTEXT.md` + `docs/PARALLEL_DEVELOPMENT.md` (nothing else) | `plans/active_plan.yaml` + `plans/active_plan.md` |
| **Phase 0 Builder** | Mid tier (or the Planner again) | The plan's `phase_0` section | Migrations + entity models + tools (1:1 from the plan) |
| **Executors** (×N) | Cheap / local models | The canonical prompt (below) — never files | Exactly 2 files each: 1 plugin + 1 test |
| **Coordinator** | You, or a mid-tier AI | Plan + checklist | Dispatches executors, runs tests, updates checkboxes |

```
[Your Request]
      │
      ▼ Step 1 (prompt)
 ┌──────────┐   generates: plans/active_plan.yaml (contract)
 │ Planner  │              + plans/active_plan.md (checklist)
 └──────────┘
      │ Step 2 (command): validate → zero errors
      │
 ─ ─ ✂ ─ ─  SESSION BOUNDARY: close the planning session.
      │      Execution runs FRESH — it reads only the two plan files.
      │
      ▼ Step 3 (prompt)
 ┌──────────┐   builds migrations/models/tools FROM the plan,
 │ Phase 0  │   then you boot ONCE → AI_CONTEXT.md regenerates and FREEZES
 └──────────┘
      │ Step 4 (prompt ×N, same prefix)
      ▼
 ┌──────────┐   each writes 1 plugin + 1 test (parallel)
 │Executors │
 └──────────┘
      │ Step 5 (commands): pytest + lint → reconstruct failures
      ▼
    Done when AI_CONTEXT.md == plan
```

---

## Step 1 — Prompt the Planner (iterative — this is a conversation)

Planning is the ONE phase where back-and-forth is expected: propose, question,
correct, re-validate — as many rounds as the design needs. Iterating is cheap
(the session's context is served from cache on every round). The session ends
when the plan validates with zero errors.

**Everything decided in the conversation must land in the YAML.** The plan is
the only artifact that survives this session — a decision that lives only in
the chat is a decision that was never made. Before closing, send the Planner
one last message: *"Re-read plans/active_plan.yaml and confirm every decision
we made in this conversation is written in it. List anything missing."*

Copy-paste to start (fill in `<REQUEST>`):

```markdown
You are the Lead Architect (Planner AI). Your task is to design a self-contained implementation plan for the following request:

<REQUEST>
[Insert feature request, e.g., "Allow users to cancel orders and automatically trigger refunds"]
</REQUEST>

### INSTRUCTIONS:
1. Your ENTIRE reading set is exactly two files — do not open anything else:
   - AI_CONTEXT.md — existing tables, routes, tools, and events.
   - docs/PARALLEL_DEVELOPMENT.md — the formal plan format, "Plan sizing" rules, and the 15 validity rules.
   You must NOT read `domains/`, `tools/`, or `tests/` source code. Everything a plan needs is in those two files.
2. Write the formal YAML plan to `plans/active_plan.yaml` following the "Formal plan format":
   - `phase_0.migrations` with `tables:` ownership AND `columns:` (every column name, SQL type, constraints).
   - `features`: one per plugin — route, request/response fields, `db:` contract, dependency tools (`mocks`), events with exact payload keys and types, `test` path.
   - `flows`: ONLY if events cross plugins — happy path, retries, idempotency tests, DLQ watchers.
3. The plan must be PROPORTIONAL to the request ("Plan sizing" section): omit `phase_0` if no new tables, omit `flows` if no events. A domain with 3 CRUDs and one event chain is ~80-120 lines of YAML, written in ONE pass.
4. Write the execution checklist to `plans/active_plan.md` (one `[ ]` entry per phase-0 artifact and per feature).
5. Do NOT write any Python or SQL files. Only the two plan files.
```

## Step 2 — Validate the plan (command)

The app must be running (`uv run main.py`). Zero `errors` before building
anything; `warnings` are advisory (e.g. a table missing its `columns:`).
An invalid plan goes BACK to the Planner — never patch it in code.

```bash
jq -Rs '{plan_yaml: .}' plans/active_plan.yaml | \
  curl -s -X POST -H "Content-Type: application/json" -d @- \
  http://localhost:5000/system/plan/validate
```

---

## ✂️ Session boundary — close planning, execute fresh

When Step 2 returns zero errors, **close the planning session**. Steps 3-5 run
in a NEW session (or new AIs entirely) that never sees the planning
conversation — it reads only `plans/active_plan.yaml` + `plans/active_plan.md`.

Why: the planning chat is full of discarded options and corrections that are
dead weight (and noise) for execution; the executors' prompt stays minimal and
deterministic. The checklist is the state machine — if execution is
interrupted, a third session resumes from the checkboxes without re-reading
anything else.

---

## Step 3 — Prompt the Phase 0 Builder, then boot ONCE

Skip this step entirely if the plan has no `phase_0` (no new tables/tools).

```markdown
You are the Phase 0 Builder. Read ONLY `plans/active_plan.yaml`.
Build exactly what its `phase_0` section declares:
1. Tools (only if `phase_0.tools` is non-empty) — follow `.agent/workflows/new-tool.md`.
2. One SQL migration file per `phase_0.migrations` entry, with the columns EXACTLY as `columns:` declares them — never invent or rename a field. Use `-- depends:` where the plan orders migrations.
3. One Pydantic entity model per `phase_0.models` entry, mirroring its table's columns 1:1.
Do NOT write any plugin or test. When the files are written, stop.
```

Tools and migrations+models are independent at write time (disjoint files) —
you can split them into two agents in any order, or run them in parallel.
What is NOT optional: **boot only after everything is written** — the boot
puts the new tools' interfaces into `AI_CONTEXT.md`, which every wave
executor receives.

Then you (the human) boot once and freeze:

```bash
uv run main.py --boot-tool db   # applies migrations, regenerates AI_CONTEXT.md
```

**From this moment until Step 5, nothing boots the app.** `AI_CONTEXT.md`
and the plan are now frozen — that is what makes the executor prefix cacheable.

## Step 4 — Dispatch the Executors (canonical prompt)

Every executor gets the **same byte-identical prefix** and only the final
line changes. Assemble each prompt with one command:

```bash
build_executor_prompt() {
  cat AI_CONTEXT.md plans/active_plan.yaml
  printf '\nImplement feature %s from the plan above.\n' "$1"
}

build_executor_prompt CreateOrderPlugin > /tmp/executor_1.txt
build_executor_prompt CancelOrderPlugin > /tmp/executor_2.txt
# one extra executor per flow writes its e2e + sad-path tests:
{ cat AI_CONTEXT.md plans/active_plan.yaml
  printf '\nImplement the flow tests for flow %s from the plan above.\n' order-lifecycle
} > /tmp/executor_flow.txt
```

Paste each file as the full prompt of one executor (local model, API, or any
agent). Rules:

- **Dispatch the first executor, let it start responding, then fire the rest** —
  a prefix-cache entry being written is not yet readable: N simultaneous cold
  requests ALL pay the full prefix. From the second executor on, any engine
  with prefix caching skips re-processing the shared block (~90% of the prompt).
- **Local engine (llama.cpp / Ollama)? Run the wave sequentially on ONE slot.**
  KV caches are per-slot — parallel slots do NOT share the prefix, while
  consecutive requests on one slot reuse it fully. You lose no real time: a
  single GPU is the bottleneck either way. "Parallel" means the features are
  independent (any order works), not that they must run simultaneously.
- **Never** put per-executor content before or inside the shared block, and
  never edit `AI_CONTEXT.md` or the plan mid-wave — one changed byte
  re-processes everything for every following request. (The executor rules
  and templates ride inside `AI_CONTEXT.md` as its "Plugin Authoring Guide"
  section, embedded at boot from `tools/context/authoring_guide.md`.)
- One feature = one executor. Never two executors on the same feature.
- **Each executor is a FRESH conversation.** Never reuse a chat that already
  produced another feature: its output would sit in the context of the next
  task (paying tokens for it) and — worse — the executor would SEE another
  feature's implementation, breaking black-box isolation. On a local engine,
  reset the conversation between features on the same slot: the KV cache
  still reuses the shared prefix (it re-computes only from the task line),
  so you get a clean context AND a warm cache at the same time.

## Step 5 — Verify, mark, reconstruct

When all executors finish:

```bash
uv run -m pytest            # full suite in one go
uv run main.py              # integration boot
curl -s http://localhost:5000/system/lint   # zero warnings, no UNTYPED_PAYLOAD
```

- **Passing feature** → mark its checkbox `[x]` in `plans/active_plan.md`.
- **Failing feature** → **delete** its two files, keep the checkbox `[ ]`,
  and dispatch a FRESH executor with the same canonical prompt (never ask an
  executor to "fix" its own output — rewrite from scratch). Optionally append
  ONE line after the task line with the failure gist (e.g. `Note: a previous
  attempt failed with "KeyError: user_id" — check the payload keys the plan
  declares.`) — it sits after the shared prefix, so the cache is untouched.
- **Two strikes → it's the plan, not the agent.** If the same feature fails
  twice with fresh executors, the contract is ambiguous or wrong: take the
  failure back to the Planner (a short planning session) and fix the plan,
  then re-dispatch. Do not keep re-rolling executors against a broken contract.
- Repeat until every checkbox is `[x]`.

**Done when the regenerated `AI_CONTEXT.md` matches the plan** (routes,
events, payload keys).

Then **archive the completed plan** instead of overwriting it:

```bash
mkdir -p plans/archive
mv plans/active_plan.yaml plans/archive/$(date +%F)-<name>.yaml
mv plans/active_plan.md   plans/archive/$(date +%F)-<name>.md
```

Planning conversations die with their sessions — archived plans are the
project's decision history. The next request starts a new plan (scale ladder
in `AGENTS.md`); the validator checks it against the live system, so plans
accumulate over time without colliding with what previous plans built.

---

## Operator checklist

- [ ] Request matched to the right workflow (scale ladder in `AGENTS.md`)
- [ ] Plan written by the Planner (one pass, proportional)
- [ ] `POST /system/plan/validate` → zero errors
- [ ] Phase 0 built 1:1 from the plan → booted ONCE → `AI_CONTEXT.md` frozen
- [ ] Executors dispatched with the canonical prompt (first one warm-up, then the rest)
- [ ] `uv run -m pytest` green, `GET /system/lint` clean
- [ ] Failures reconstructed with fresh executors (files deleted, not patched)
- [ ] `AI_CONTEXT.md` == plan → mark done
