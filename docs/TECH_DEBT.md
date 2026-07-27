# Technical debt

What is knowingly unfinished, and what it would cost to finish. Everything here
was verified — nothing is listed on suspicion. Items that are *decisions* rather
than debt live in [ROADMAP.md](../ROADMAP.md); this file is only what someone
would reasonably expect to work and does not, or works in a narrower way than it
looks.

Recorded 2026-07-27, after Issue 39 (Core as an installable package).

---

## 1. `auth` is materialized by default — should it be an extra?

`tools/auth` and the users starter ship in every scaffolded project. Nothing
hard-depends on them: `http_server_tool` takes `auth_validator` as an optional
**callback**, so it never imports auth. Verified — auth could become a
tool+domain pair in `extras/` exactly like the scheduler, installed with
`microcoreos add auth`.

Arguments both ways, and this is a product call:

- **For an extra:** you install auth if you need auth. It drags a `users`
  table, a roles model and a JWT flavour into projects that may want none of
  it, and it makes `AUTH_SECRET_KEY` a hard boot requirement.
- **Against:** unlike redis or kafka, auth needs no external service, and a web
  framework whose default project cannot log anyone in is a strange default.

**Cost:** the same shape as the scheduler move — two folders, a catalog entry,
`.env` keys, doc sweep. Half a day. **Why open:** nobody has decided.

**Resolved on the way here:** a fresh project used to boot with a
`FieldDivergenceLinter` WARN, because the auth starter materializes both
`login_plugin` (`password.min_length=1`) and `create_user_plugin` (`=8`). The
linter's docstring always said divergence "CAN be legitimate — confirm it is on
purpose", but there was nowhere to record the confirmation, so the warning was
permanent and the linter was on its way to being tuned out. Declarations can
now waive themselves where they happen:

```python
password: str = Field(
    min_length=1,
    json_schema_extra={"divergence_ok": "login verifies against the hash; "
                                        "length policy belongs to registration"},
)
```

A waived declaration drops out of the comparison rather than silencing the
field, so waiving login does not blind the linter to create-vs-update
disagreeing — and a waiver with an empty reason is not honoured. Three tests
pin all of that. A scaffolded project now boots with zero warnings.

---

## 2. `microcoreos upgrade` — three things it does not do

Verified working: safe updates, conflict refusal, tracking an extra to where
`add` or a hand `mv` put it. Not covered:

| Gap | Consequence |
|---|---|
| Files deleted upstream are reported, never removed | A tool dropped from the framework lingers in your project until you delete it |
| A folder renamed to anything but the conventional destination loses tracking | `mv extras/available_tools/postgresql tools/my-db` → upstream fixes never arrive, silently |
| Only exercised on Linux / CPython 3.12 | Manifest paths are normalized to `/` for Windows, but that path has never been run |

The second is the same failure shape as the bug fixed in this session (a silent
"everything is current"), just triggered by a rename the convention cannot
predict. A `moved` entry can be written by hand into
`.microcoreos/manifest.json` as a workaround.

---

## 3. `microcoreos add` has never resolved against a real index

`uv add 'microcoreos[postgres]'` works in every test because the package is a
**local path dependency** already in the lockfile. Against a published PyPI
release the resolution path is different and untested. The CI job passes
`--no-install` for exactly this reason.

**Cost:** one CI run after the first publish. **Why open:** nothing is published.

---

## 4. The flaky nobody has reproduced

`tests/test_chaos_control.py::test_pause_accumulates_durable_backlog_and_drains`
failed once. It did not reproduce in 21 isolated runs, 15 full-suite runs, or
under CPU contention.

Ruled out by reading: the driver's prune (`PRUNE_EVERY=128`, the test publishes
3 times), the paused-plugin identity resolution (deterministic), and delivery
ordering on resume (the durable driver's reader is sequential).

Two readings remain, and **which one is true is unknown**: test impatience, or a
real race in the pause/resume path — in which case a "paused" plugin could
receive a message during a maintenance pause, or the backlog fail to drain.

Blast radius if real: the pause mechanism (`_paused_owners`) ships in the
default `event_bus` and `http` tools, but nothing ever populates that set except
the chaos plugin, which lives in `extras/` and is not materialized. So it is an
opt-in ops feature, not the default request/event path.

**State:** the test's one fragile timing assumption was removed, and both it and
the shared `wait_until` helper now report the observed state on timeout instead
of `<lambda at 0x...>` — which is why the original failure could not be
diagnosed. A recurrence will say which condition and with what values.

---

## 5. 37 hand-built tools across 27 test files

`tests/conftest.py` now publishes a fixture per Kernel injection key (`db`,
`event_bus`, `auth`, `state`, `logger`, `config`), so a test asks for tools the
way a plugin does. 37 call sites across 27 files still construct
`SqliteTool()` / `EventBusTool()` / etc. inline (measured 2026-07-27,
excluding the shared fixtures themselves).

Nothing is broken — a local fixture always overrides the shared one — so this
is redundancy, not breakage. Best first candidate:
`tests/test_durable_one_shots.py`, which repeats the most scaffolding and would
serve as a second worked example next to
`tests/test_plugin_di_fixtures.py`.

---

## 6. Docs still speak only of `uv run main.py`

`AGENTS.md`, `.agent/workflows/*` and several `docs/` pages instruct
`uv run main.py`. That is correct — `main.py` is materialized and is a shim over
the same code path — but none of them mention the installed `microcoreos`
command, which is how a packaged install is actually driven.
[CLI.md](CLI.md) documents the command; the older pages were not swept.

---

## 7. Compatibility surface, frozen at the first publish

Nothing is released, so everything so far has been free to rename. From the
first upload onward, three things become breaking to change:

- The five names re-exported from `microcoreos/__init__.py` (`BasePlugin`,
  `BaseTool`, `ToolUnavailableError`, and the two context vars) — every
  generated plugin imports them.
- The `[project.optional-dependencies]` extra names — `microcoreos add` and
  every doc reference them by string.
- The `.microcoreos/manifest.json` format. Readers already tolerate missing
  keys (`.get("moved", {})`) and must keep doing so.

---

## 8. Not debt, but unfinished by choice

- **PyPI publishing** — account, name, token, release workflow. Blocks the
  README's Quick Start from being literally true.
- **`domains/users` CRUD half** (list, get-by-id, update, delete, logout, the
  event consumer) stays in the repo and is not materialized. Deliberate: that
  is CRUD you write for your own entities.
- **Mocked tests verify against a contract the test itself declares.** If a
  tool's real API drifts, the mock keeps passing. Covered elsewhere by design —
  `ToolDocDriftLinter` and the parity suites — not by the plugin test.
