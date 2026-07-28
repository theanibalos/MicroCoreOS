# Technical debt

What is knowingly unfinished, and what it would cost to finish. Everything here
was verified — nothing is listed on suspicion. Items that are *decisions* rather
than debt live in [ROADMAP.md](../ROADMAP.md); this file is only what someone
would reasonably expect to work and does not, or works in a narrower way than it
looks.

Recorded 2026-07-27, after Issue 39 (Core as an installable package). Items 1,
2, 5 and 6 were closed the same day. Nothing left in this file is code anyone
can write today: item 3 is blocked on publishing, item 4 is waiting for a
failure to happen again, and items 7 and 8 are notes rather than work — see
each.

---

## 1. `auth` is materialized by default ✅ CLOSED — it is an extra now

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

**Decided:** an extra. `microcoreos add auth` installs the tool, the four
plugins that ARE auth — register, login, who-am-I, logout — and the model and
migration. A fresh project has no users table, no JWT and no `AUTH_SECRET_KEY`
requirement. `bcrypt` and `pyjwt` moved out of the base install into a new
`auth` extra, which is the point: nothing but auth imported them.

`logout` is new to what ships. It was in the repo and never materialized, so
every scaffolded project had a login with no way out — it costs nothing
(`http` and `logger`, clears the cookie) and it is half of login's contract.
The CRUD (list, get-by-id, update, delete) and `welcome_service`, the
bus-consumer example, stay in this repo: item 8's reasoning, unchanged.

Two things this move surfaced, both now pinned by tests:

- **`new` had two allowlists and nothing kept them in sync.** From a checkout
  it walks `scaffold.RUNTIME_ENTRIES`; from the wheel it gets whatever
  `force-include` placed under `_template/`. hatchling's `force-include`
  ignores the `exclude` list, so the first attempt shipped 4 plugins packaged
  and 9 from a checkout — green suite, wrong artefact.

  There is one list now. `hatch_build.py` is a build hook that derives the
  wheel's payload from `RUNTIME_ENTRIES + AI_KIT_ENTRIES`, and the pyproject
  table is gone. Two tests hold the line: one asserts nobody hand-writes a
  second copy, the other that every entry names something that exists — a typo
  in that list does not fail a build, it silently ships one file fewer.

  The hook puts `self.root` on `sys.path` before importing: the build is
  isolated, so the package being built is not importable by default. Safe
  here because `scaffold` reaches only `os`, `shutil` and `upgrade`, and
  `upgrade` reaches only the standard library — no runtime dependency is
  dragged into the build environment. Keep it that way.
- **The catalog's `AUTH_SECRET_KEY` placeholder was 24 characters** and
  `AuthTool` refuses anything under 32 — `add auth` produced a project that
  died on its first boot. Caught by running the wheel end to end, not by the
  suite. `test_catalog.py` builds the real tool with the real placeholder now,
  rather than asserting a length: repeating the 32 in a test would be the same
  duplication that caused the bug, and the catalog's job is to write a value
  that WORKS, not one of a given size.

**`ping` went with it.** AGENTS.md sends every agent to
`domains/ping/plugins/ping_plugin.py` for the shape of a plugin with no
database — a path that existed in this checkout and in no project ever
scaffolded from it, since the demo domain was never materialized. No shipped
domain was a substitute: `system` is introspection and `devtools` is linters.
It is `extras/available_domains/ping` now, readable in every project and
installable with `microcoreos add ping`, because a live `/ping` in production
is somebody's incident.

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

**It paid for itself on its first run**, and not with the backslash it was
written to catch. Two locale bugs came out instead, both invisible on Linux
because there the default encoding *is* UTF-8:

- 82 `read_text()` / `write_text()` / `open()` calls across `tests/` had no
  explicit encoding. On Windows that is cp1252, and the first scaffolded file
  with an em dash in it fails to decode. All 82 now pass `encoding="utf-8"`,
  and ruff's `PLW1514` is selected in `pyproject.toml` so the next one cannot
  merge. (Shipped code was already explicit throughout; this was tests only.)
- Worse, and never reached because the suite failed first: the CLI itself
  crashed. Every success message it prints carries an emoji or an em dash, and
  a redirected stdout on Windows — a pipe, a file, CI — encodes as cp1252, so
  `microcoreos new` raised `UnicodeEncodeError` on its own last line.
  `cli._stdio_speaks_unicode()` reconfigures the stream at entry; a real
  Windows console already reports utf-8, so it is a no-op there and everywhere
  else. `tests/test_cli.py` pins it against a cp1252 stream, on any platform.

**Still not covered:** *booting* on Windows. The job stops at the CLI and
filesystem surface on purpose — the boot half needs service containers Windows
runners do not offer.

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

**It recurred on 2026-07-28**, in CI, on `test (3.12)` — and the
instrumentation did its job. What the failure reported:

```
observed: {'seen': [{'n': 1}, {'n': 0}, {'n': 2}], 'rows': 0}
```

That narrows it a long way, and mostly in the reassuring direction:

- **All three messages were delivered and the backlog drained to zero.** Not a
  lost message, not a stuck queue, and not test impatience — `rows: 0` is the
  terminal state, not a partial one caught too early.
- **The pause held.** `victim.seen == []` during the pause passed, as did
  `rows == 3`. The scarier of the two readings above — a "paused" plugin
  receiving a message mid-pause — is **ruled out by observation** now, not by
  reading.
- **The only thing wrong was the order**: 1, 0, 2 instead of 0, 1, 2.

So what is left is one question, and it is a contract question rather than a
bug report: **does this bus promise ordered delivery on resume?** The test
asserts it and the docstring says "drains in order". Two facts bear on it, both
verified in the source rather than assumed:

- The subscription is not a broadcast, so it takes a group and goes through the
  durable `_reader`, which claims `ORDER BY id LIMIT 1` and awaits
  `asyncio.shield(delivery)` before claiming the next row. Sequential by
  construction — the earlier note in this file was right about that.
- The pause is a per-delivery polling loop in `_do_deliver`
  (`while paused: await asyncio.sleep(0.2)`). Whatever reorders these two
  deliveries has to get more than one of them parked in that loop at once,
  because two tasks waking from independent 200 ms sleeps have no defined
  order between them.

**The contract question is already answered, and not in the test's favour.**
`sqlite_driver.py`'s header states it as a guarantee:

> `key / priority` → accepted but no-ops (**the queue is totally ordered**, no
> message priority) — same degradation as Redis Streams.

`key` — documented in `docs/EVENT_BUS.md` as the partition key for ordered
delivery — is a no-op on this driver *because* total ordering makes it
redundant. So the test asserts exactly what the driver promises, and the
observed 1, 0, 2 is a defect rather than an over-assertion.

That also raises the cost of the easy fix. Relaxing the assertion to a set
would not just hide this: it would quietly turn `key="customer_42"` into a
silent no-op for anyone who writes it expecting per-customer ordering, since
the justification for ignoring the key is the guarantee this failure breaks.

**Still do not "fix" it blind.** Reading has gone as far as it goes. The reader
is sequential — it claims one row and awaits `asyncio.shield(delivery)` before
claiming the next — so a single subscription should never have two deliveries
in flight, and yet two of them demonstrably interleaved. The next step is an
instrumented run that shows how, not a change to the assertion. Pruning
(`PRUNE_EVERY=128` against 3 publishes), retries (`retries=0`) and due-time
skew (everything due immediately) are all ruled out.

---

## 5. 37 hand-built tools across 27 test files → 19 across 12 ✅ CLOSED

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

The one genuine near-miss is now closed. `test_durable_one_shots.py` kept its
local `db` because its migration lives in
`extras/available_domains/scheduler/migrations/` and the marker only resolved
`domains/<name>/migrations`. The marker now searches both roots, `domains/`
first so a materialized domain wins over the extra it was installed from — the
same rule the `db` fixture already follows in resolving the ACTIVE tool. The
test declares `@pytest.mark.migrations("scheduler")` and builds nothing;
`microcoreos add scheduler` would move the folder without touching it. That
takes the count to **19 call sites across 12 files**, and everything left is
one of the three groups above.

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
