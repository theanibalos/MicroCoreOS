# The `microcoreos` command

Installed by the package. Five commands for the project lifecycle, four for the
plan pipeline.

```
microcoreos new <path> [--force] [--no-ai-kit]   Materialize a new project
microcoreos add <extra> [--no-install]           Install an extra completely
microcoreos upgrade [--apply]                    Report/apply upstream changes
microcoreos [run] [--boot-tool <tool>]           Boot the Kernel
microcoreos dev                                  Boot with auto-reload

microcoreos status                               Active plan, progress, manifest age
microcoreos plan validate [path]                 The 16 plan rules, offline
microcoreos migrate                              Migrations + regenerate AI_CONTEXT.md
microcoreos schema                               The live tables and columns
```

**Every example below needs a `uv run` prefix** (or an activated venv): the
console script lives in `.venv/bin`, so a bare `microcoreos` is "command not
found". And `<angle brackets>` mark a placeholder — type the value, not the
brackets.

Except for `new`, run them from the root of a project — the directory holding
`tools/`, `domains/` and `plans/`. Running elsewhere is refused rather than
booting an empty system and calling it Ready.

---

## `microcoreos new <path>`

Copies the framework's source into your directory: `tools/`, `domains/system`,
`domains/devtools`, `extras/`, `plans/`, `dev_infra/`, `main.py`, `Dockerfile`,
`.env.example` — plus the AI kit (`AGENTS.md`, `INSTRUCTIONS_FOR_AI.md`,
`.agent/`, `docs/`).

One list decides all of it: `scaffold.RUNTIME_ENTRIES`. The wheel's copy under
`_template/` is generated from that same list by `hatch_build.py`, so what a
checkout copies and what the package ships cannot disagree.

**Why copied instead of imported.** Installing and swapping infrastructure here
IS file placement (`mv extras/available_tools/postgresql tools/`, dropping a
`{name}_driver.py` into `tools/event_bus/`). None of that works against
`site-packages`: it may be read-only, and anything written there is wiped by
the next upgrade. Only the Kernel — `microcoreos/` itself — stays in the
package.

It also writes, only when absent: `.env` (from `.env.example`),
`pyproject.toml`, and a `README.md` for the project. An existing one is never
overwritten, so `uv init && uv add microcoreos && microcoreos new .` works.

| Flag | Effect |
|---|---|
| `--force` | Materialize even if `tools/` or `domains/` already exist |
| `--no-ai-kit` | Skip `AGENTS.md`, `INSTRUCTIONS_FOR_AI.md`, `.agent/`, `docs/` |

**Not materialized:** `ping` (the hello-world) and auth. A fresh project has no
`tools/auth` and no `domains/users` — no users table, no JWT, and no
`AUTH_SECRET_KEY` to set before it will boot. `http_server_tool` takes
`auth_validator` as an optional callback and never imports auth, so nothing
misses it.

`microcoreos add auth` installs it: the tool, plus the four plugins that ARE
auth — `create_user`, `login`, `get_me`, `logout` — with the model and the
migration. The CRUD around them (list, get-by-id, update, delete) is not
shipped: that is what you write for your own entities.

---

## `microcoreos add <extra>`

Activating an extra is three acts, and skipping any one fails somewhere
different:

| Act | Skipping it |
|---|---|
| Install the optional dependency | `No module named 'asyncpg'` at boot |
| Move the source into `tools/`/`domains/` | Nothing happens — discovery only sees those directories |
| Add its settings to `.env` | Boots, then connects nowhere |

This does all three:

```bash
microcoreos add postgres
```

```
📦 Installing extra 'postgres'

   $ uv add 'microcoreos[postgres]'
   ✓ extras/available_tools/postgresql → tools/postgresql
   ✓ .env += PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE
```

Available: `auth`, `ping`, `postgres`, `redis`, `s3`, `scheduler`, `kafka`,
`rabbitmq`, `chaos`. Run `microcoreos add` with no argument to list them.

`auth` and `ping` are the two that need no external service. `auth` is an extra
because a users table, a roles model and a JWT flavour are not something a
framework should impose; `ping` is a single `GET /ping` you read for the shape
of a minimal plugin and then delete.

Three rules it follows:

- **The tool moves before its domain.** A plugin cannot exist without the tool
  it asks for, so the other order leaves a boot that aborts the plugin.
- **Drivers are not tools.** `kafka` and `rabbitmq` do not become
  `tools/kafka/`; the `*_driver.py` drops into `tools/event_bus/` and `.env`
  gets `EVENT_BUS_DRIVER=kafka`.
- **`.env` is never overwritten.** A value already there is your decision.
  Re-running `add` is a no-op.

`uv add` runs only when there is a `pyproject.toml` and `uv` is on PATH —
otherwise the command is printed for you to run. `--no-install` skips that step.

---

## `microcoreos upgrade`

The mitigation for honest vendoring: your tools and domains are your source, so
a fix upstream does not reach them on its own.

`new` records the SHA-256 of every file it writes in
`.microcoreos/manifest.json`. That baseline is what makes three otherwise
indistinguishable states distinguishable:

| local | upstream | verdict |
|---|---|---|
| = baseline | changed | **safe to update** — you never touched it |
| changed | = baseline | **yours** — left alone, always |
| changed | changed | **conflict** — reported, never written |
| = baseline | withdrawn | **deleted** — the framework's file to take back |
| changed | withdrawn | **released** — kept, and no longer tracked at all |

```bash
microcoreos upgrade            # report only (default)
microcoreos upgrade --apply    # write the safe ones, move the baseline
```

`--apply` never touches a conflict and never resurrects a file you deleted —
removing a tool you do not use is a supported act, not damage.

**A file dropped upstream is deleted here, unless you edited it.** The rule is
the same one as everywhere else: untouched is the framework's to withdraw, and
an empty `tools/<name>/` goes with the last file in it. If you did edit it, it
stays and leaves the baseline for good — upstream no longer ships it and you
changed it, so there is nothing left to compare, and re-reporting it on every
run would just teach you to skip the output.

If most of the baseline appears to have vanished, nothing is deleted: that is
what a partial or broken install looks like, not what a release looks like.

**The manifest belongs in version control.** The scaffolded `.gitignore` does
not exclude it on purpose: a teammate who clones the project without it cannot
upgrade, because their edits would be indistinguishable from stale files.
Without a manifest the command refuses outright — it is written by
`microcoreos new`, and its absence is an error rather than a degraded mode.

**Extras you installed are tracked to where they moved.** `microcoreos add`
records the move, and the baseline stays keyed by the file's upstream path —
so a fix to `extras/available_tools/scheduler/` reaches `tools/scheduler/`
where you actually put it.

Moving a folder yourself works too, including to a name no convention could
guess (`mv extras/available_tools/postgresql tools/my-db`). Names cannot follow
that, so content does: an unedited file still hashes to its baseline digest
wherever it now sits, and the move is written into the manifest the first time
`upgrade` runs — after which the folder is tracked by name and you can edit it
freely. A digest matching more than one candidate proves nothing and is
ignored, so nothing is claimed on a guess.

---

## `microcoreos run` / `microcoreos dev`

`microcoreos` alone is `microcoreos run`. Identical to `uv run main.py` —
the root `main.py` is a shim over this same code path, so both are the same
boot.

```bash
microcoreos                          # boot
microcoreos run --boot-tool db       # boot ONE tool in isolation, then exit
microcoreos dev                      # boot, reload on .py changes
```

`--boot-tool` is the **deployment** migrations entry point:
`DB_AUTO_MIGRATE=true microcoreos run --boot-tool db` — see
[ELASTIC_DEPLOYMENT.md](ELASTIC_DEPLOYMENT.md). It boots that tool and nothing
else, which is exactly right for a pipeline that wants migrations applied and
no side effects — and exactly wrong for phase 0 of a plan, where the point is
also to refresh `AI_CONTEXT.md`. Use `microcoreos migrate` there.

---

## The plan pipeline

Four commands covering the plan workflow in
[PARALLEL_DEVELOPMENT.md](PARALLEL_DEVELOPMENT.md). Each replaces a sequence
agents previously had to improvise, and each of those improvisations was
observed failing.

```bash
microcoreos status                   # before anything else
microcoreos plan validate            # defaults to plans/active_plan.yaml
microcoreos plan validate draft.yaml # or any path
microcoreos migrate                  # after writing phase 0
microcoreos schema                   # verify what landed in the database
```

**`status`** — the preflight. Which plan is active (and whether it is still the
shipped template), how many checklist tasks remain, and whether `AI_CONTEXT.md`
is older than the newest file under `domains/` or `tools/`. It also names any
other `plans/*.yaml` sitting there, because those are plans nothing executes,
and any loose `.py` in the project root — every deliverable has a declared home
under `domains/`, `tools/` or `tests/`, so one at the root is an agent's
scratch file left behind. Reported, never deleted.

**`plan validate`** — the 18 rules with no server running. The rules were
always pure; only the live snapshot needed a booted system, and everything in
it except live *subscribers* can be read off the disk. Errors carry the YAML
that fixes them. Exit code 1 on errors, 0 on valid.
`POST /system/plan/validate` runs the identical rules against a booted system
and adds those live subscribers — use it when a `dlq_watcher` or a compensation
consumer only exists at runtime.

**`migrate`** — the boot with an ending. `uv run main.py` regenerates the
manifest too, but never returns: in the foreground it hangs the agent's
session, in the background it gives no signal that the manifest is written and
leaves the process behind. That gap is why the docs used to prescribe
`--boot-tool db` here, which exits but never reaches the context tool.

It boots FULLY (with `DB_AUTO_MIGRATE=true`) and shuts down. Full, because the
manifest is generated from the live container: a partial boot would rewrite
`AI_CONTEXT.md` as a system with no tools and no plugins. If the port is
already held it says so and stops, rather than letting uvicorn kill the
process with `sys.exit(1)` from inside its startup — phase 0 expects nothing
booted, so that is a wrong-state message, not a missing capability.

**`schema`** — the live tables and columns, read through the db tool's
`describe_schema()`. Through the tool, not around it: the types come back in
the closed vocabulary every engine shares, so this is what an engine swap has
to preserve. A raw `sqlite3` probe answers a different question, and is usually
not installed anyway.

`dev` needs `watchfiles` (`uv add --dev watchfiles`); it says so if missing.

**Two things the command does that `python main.py` gets for free.** A console
script starts with the venv's `bin/` as `sys.path[0]`, not your project, so the
project root is inserted explicitly — without it every `import tools.*` fails
and the Kernel reports an empty system as Ready. And `.env` is loaded by
explicit path, because bare `load_dotenv()` searches upward from its *caller*,
which installed is `site-packages`, not your project.
