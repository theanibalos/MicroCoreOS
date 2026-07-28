# The `microcoreos` command

Installed by the package. Five commands: create a project, install an extra,
see what changed upstream, boot, boot with reload.

```
microcoreos new <path> [--force] [--no-ai-kit]   Materialize a new project
microcoreos add <extra> [--no-install]           Install an extra completely
microcoreos upgrade [--apply]                    Report/apply upstream changes
microcoreos [run] [--boot-tool <tool>]           Boot the Kernel
microcoreos dev                                  Boot with auto-reload
```

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

`--boot-tool` is the migrations pipeline entry point:
`DB_AUTO_MIGRATE=true microcoreos run --boot-tool db` — see
[ELASTIC_DEPLOYMENT.md](ELASTIC_DEPLOYMENT.md).

`dev` needs `watchfiles` (`uv add --dev watchfiles`); it says so if missing.

**Two things the command does that `python main.py` gets for free.** A console
script starts with the venv's `bin/` as `sys.path[0]`, not your project, so the
project root is inserted explicitly — without it every `import tools.*` fails
and the Kernel reports an empty system as Ready. And `.env` is loaded by
explicit path, because bare `load_dotenv()` searches upward from its *caller*,
which installed is `site-packages`, not your project.
