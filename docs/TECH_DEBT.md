# Technical debt

What is knowingly unfinished, and what it would cost to finish. Everything here
was verified — nothing is listed on suspicion. Items that are *decisions* rather
than debt live in [ROADMAP.md](../ROADMAP.md); this file is only what someone
would reasonably expect to work and does not, or works in a narrower way than it
looks.

Recorded 2026-07-27, after Issue 39 (Core as an installable package). Items 2
and 6 were closed the same day, and item 5 reduced to what should stay as it
is. Items 1 and 3 are blocked on decisions, not on work — see each.

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

## 2. `microcoreos upgrade` — three things it did not do ✅ CLOSED

All three are done. Verified against the built wheel in a clean venv, not only
from the checkout — the packaged path is the only one where the last three
bugs here were reachable.

**Files withdrawn upstream are now removed.** The same rule as everywhere else
decides: untouched is the framework's file to take back, so `--apply` deletes
it and prunes the folder if it was the last file in it. A file you *edited*
that upstream dropped is kept and **released** — it leaves the baseline for
good, because upstream no longer ships it and you changed it, so there is
nothing left to compare. Reporting it forever instead would have built the
permanent, tune-out-able warning this document complains about in item 1.

One hazard the feature creates and had to close: withdrawal reads the ABSENCE
of a file as an instruction, so a partial wheel is indistinguishable from a
release that deleted everything. Past `MAX_REMOVAL_SHARE` (25%) of the
baseline, nothing is withdrawn and the template is called broken instead.

**A folder renamed off-convention is found by content.** Names cannot follow
`mv extras/available_tools/postgresql tools/my-db`, but the baseline digest
can: an unedited file still hashes to it wherever it sits. A match is claimed
only when a digest names exactly one missing baseline file AND exactly one file
on disk — every empty `__init__.py` shares a digest, and a duplicated (rather
than moved) extra would too, so ambiguity proves nothing and is dropped. The
move is then written into the manifest on sight, in dry-run mode too, because
editing the file destroys the only evidence; and the *folder* move is recorded
rather than the file move, so files upstream adds to that extra later still
land in the right place. The hand-written `moved` entry is no longer a
workaround anyone needs.

**Windows now runs.** A `packaged-e2e-windows` job builds the wheel and drives
`new` → `add` → `upgrade` on `windows-latest`, asserting that no manifest path
carries a backslash — the invariant that would otherwise break every lookup on
Linux — plus the filesystem-facing suites. `tests/test_upgrade.py` pins the
same assertion so it fails locally too, though only the Windows job gives it
teeth.

**Still not covered:** *booting* on Windows. The job stops at the CLI and
filesystem surface on purpose — the boot half needs service containers Windows
runners do not offer. And this is CI added, not CI observed: it is verified on
the next push, not in the session that wrote it.

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

**Do not "fix" this without a reproduction.** There is nothing to fix until a
failure is in hand: an attempt made blind ends up adjusting the test until it
looks robust, which converts an unknown into a hidden one and throws away the
instrumentation that is the only thing standing between here and an answer.
The next move is a recurrence, not a change.

---

## 5. 37 hand-built tools across 27 test files → 20 across 13

`tests/conftest.py` publishes a fixture per Kernel injection key (`db`,
`event_bus`, `auth`, `state`, `logger`, `config`), so a test asks for tools the
way a plugin does. 15 files were converted; the same grep that measured 37 call
sites in 27 files now measures **20 in 13**. Collected test count went 639 →
654, and the 15 added are all `test_upgrade.py`'s — the refactor removed none.

The remainder is not a backlog to finish. Every one of them was looked at, and
they fall into three groups that should stay as they are:

- **Sync test files.** The shared fixtures are async generators, and pytest
  cannot resolve one for a sync test. `test_auth_tool.py` (mixed sync/async),
  `test_config_tool.py`, `test_logger_tool.py`.
- **Tests of the tool itself, not of a plugin using it.** The sqlite suites
  drive transaction locking, `_run_migrations()` and schema introspection —
  exactly what the fixture's abstraction hides. Two `AuthTool()` call sites
  exist to exercise the constructor's own validation.
- **Parity suites.** Building several drivers side by side IS the test
  (`tools/test_db_parity.py`, `test_state_parity.py`, and the driver suites).

One genuine near-miss: `test_durable_one_shots.py` keeps its local `db`
because its migration lives in `extras/available_domains/scheduler/migrations/`
and the shared fixture's `@pytest.mark.migrations` marker only resolves
`domains/<name>/migrations`. Teaching the marker about extras would close it.

---

## 6. Docs spoke only of `uv run main.py` ✅ CLOSED

Ten pages now name the installed `microcoreos` command alongside
`uv run main.py`: `README.md` and its Spanish translation, `AGENTS.md`,
`plans/README.md`, `docs/ELASTIC_DEPLOYMENT.md`, `docs/PARALLEL_DEVELOPMENT.md`,
and the four `.agent/` workflow and skill pages. `uv run main.py` stays
everywhere it was — it is correct, and it is the form that works in a checkout.

Deliberately not swept: `ROADMAP.md`'s changelog entries and
`docs/PLAN_EVENT_LINTER.md`, which are historical records rather than live
instructions, and `microcoreos/project_readme.md`, which already leads with
`microcoreos`.

Also added while in here: `AGENTS.md`'s Reading Path — the first thing any
agent reads — now points at this file. Before, a session could only find the
debt register if someone told it the path.

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
