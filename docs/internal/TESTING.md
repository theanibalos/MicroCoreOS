# Testing — running the suite, coverage, mutation

Maintainer reference for the framework's own repo. A generated project keeps
the same runner and the same fixtures, with a narrower `testpaths`.

---

## The suite

```bash
uv run -m pytest -q
```

**Never pass a path.** `testpaths` in `pyproject.toml` owns the set, and it is
wider than `tests/`:

```toml
testpaths = ["tests", "tools", "extras"]
```

A tool's own tests live inside the tool's folder so they travel with it when
`microcoreos add` moves it into `tools/`. `pytest tests/` runs green while
silently skipping every one of them — which is what CI did until the
`Run Core Tests` step dropped its path argument.

A generated project gets `["tests", "tools"]`: an extra that is not installed
sits in `extras/` and its tests do not run. Install the tool, and its tests
join your suite.

### Where a test lives

| Test of… | Lives in | Named |
|---|---|---|
| A plugin, the core, the CLI, a linter | `tests/{domains,core,system,linters}/` | `test_*.py` |
| A tool that ships in `tools/` | `tests/tools/{name}/` | `test_*.py` |
| A tool that ships as an extra | `{tool folder}/tests/` | **`{name}_tool_test.py`** |
| A parity suite (two implementations at once) | `tests/tools/{name}/` | `test_*_parity.py` |

The third row's naming is not style. The Kernel imports every `*_tool.py`
under `tools/`, so `test_s3_tool.py` gets imported at boot — and with it
pytest, which a deployed install does not have. pytest collects `*_test.py` by
default, so the safe name costs nothing. `DiscoveryNamingLinterPlugin` fails
on the unsafe one.

A test inside a tool folder imports the tool from either location, because the
folder moves:

```python
try:                                        # installed: tools/
    from tools.s3.s3_tool import S3Tool
except ModuleNotFoundError:                 # not installed: extras/available_tools/
    from extras.available_tools.s3.s3_tool import S3Tool
```

Parity suites are the exception to co-location: they import a reference AND a
replacement at once, so they belong to the contract, not to either folder.

### Fixtures

`conftest.py` is at the **repo root**, not under `tests/` — a conftest under
`tests/` does not reach `tools/*/tests/`. It publishes one fixture per Kernel
injection key, so a test's signature is the plugin's signature:

```python
@pytest.mark.migrations("users")
async def test_create_user_persists(db, event_bus, auth, logger):
    ...
```

Available: `db` (the ACTIVE db tool, engine-agnostic), `event_bus`, `auth`,
`state`, `logger`, `config`. The `@pytest.mark.migrations(*domains)` marker
applies those domains' real migration files to the `db` fixture; with no
marker you get a real, empty schema.

One autouse fixture points `EVENT_BUS_SQLITE_PATH` at a per-test `tmp_path`,
so no test touches the production queue file.

---

## Suites that need a server

They skip themselves when the backend is unreachable, so a bare `pytest` is
always green — and always incomplete. Start the infrastructure first:

```bash
podman compose -f dev_infra/docker-compose.yml up -d          # or: docker compose
podman compose -f dev_infra/docker-compose.yml up -d rustfs   # just one
```

| Service | Port | Covers |
|---|---|---|
| `rustfs` | 9000 | `tests/tools/s3/test_s3_parity.py` |
| `postgres` | 5432 | `tests/tools/db/test_db_parity.py`, the PostgreSQL tool's own tests |
| `redis` | 6379 | state parity, the Redis Streams event-bus driver |
| `kafka` | 9092 | `test_event_bus_kafka_parity.py` |
| `rabbitmq` | 5672 | `test_event_bus_rabbitmq_parity.py` |
| `jaeger` | 4317 | telemetry export, by hand |

A green run that reports **0 skipped** is the only one that exercised all of
them. Check it:

```bash
uv run -m pytest -q -rs      # -rs lists every skip with its reason
```

---

## Coverage

`pytest-cov` is in the dev group with no configuration of its own, so the
flags carry it:

```bash
uv run -m pytest -q --cov=microcoreos --cov=tools --cov-report=term
uv run -m pytest -q --cov=microcoreos --cov=tools --cov-report=html   # → htmlcov/
```

Neither `htmlcov/` nor `.coverage` is committed.

---

## Mutation

`[tool.mutmut]` in `pyproject.toml` already carries the runner and the scope:

```toml
runner = 'uv run -m pytest -x -k "not parity and not upgrade"'
source_paths = ["microcoreos/", "tools/"]
```

Parity and upgrade are excluded because they need servers or are slow, and
`-x` means one failure ends the run.

```bash
uv run -m mutmut run          # slow: copies the repo into mutants/
uv run -m mutmut results      # read the last run without re-running
uv run -m mutmut browse       # TUI
uv run -m mutmut show <id>    # the diff of one mutant
```

**Read the results before trusting them.** A run whose `killed` count is zero
while thousands "survived" almost always means the runner never started inside
`mutants/` — every mutant survives a suite that did not run. Sanity-check the
runner in the copied tree before drawing any conclusion from a report:

```bash
cd mutants && uv run -m pytest -x -k "not parity and not upgrade" -q
```

`also_copy` lists what the mutants workspace needs. It already includes
`tests`, `tools`, `extras` and `pyproject.toml`, which is what makes the
configured `testpaths` resolve in there.

---

## The linter gates

Six linters scan the **real repo** from inside the normal suite, so a
violation fails `pytest` rather than waiting for a boot:

| Test | Fails when |
|---|---|
| `test_real_repo_has_no_isolation_violations` | A domain imports another domain |
| `test_real_repo_has_no_duplicate_tables` | Two domains declare the same table |
| `test_real_repo_has_no_naming_violations` | A tool/plugin class is in a file the Kernel never imports |
| `test_real_repo_has_no_test_the_kernel_would_import` | A test is named so the Kernel imports it at boot |
| `test_real_repo_has_no_dead_paths` | A doc or docstring names a file that is not on disk |
| `test_real_repo_produces_no_false_warnings` | The event-contract analyzer disagrees with the code |

`test_real_repo_has_no_unaccepted_field_divergence` is advisory by design:
divergence can be correct, so the gate is "nothing new", against a list of
accepted cases carrying their reason.

Suppress a dead-path finding with `lint:no-path` on the line — for a path that
is correct only after `microcoreos add`, an illustrative path in an error
message, or a replacement nobody has written yet. Suppressing is a decision;
writing it on the line is how it stays reviewable.

---

## What CI runs

`.github/workflows/ci.yml`, four jobs:

| Job | What it proves |
|---|---|
| `test` | ruff, a syntax check, then the full suite with RustFS running |
| `smoke-boot` | The real system boots against real infrastructure; every tool `OK`, every plugin `READY` |
| `packaged-e2e` | `pip install` the wheel → `new` → `add auth` → boot. Catches anything that only breaks in a packaged install, where the dev dependencies are absent |
| `packaged-e2e-windows` | The CLI paths on Windows |

`packaged-e2e` is the one that catches the failures your working copy cannot
have: it runs without pytest, without the framework's repo on disk, and with
only what the wheel shipped.

The release workflow does **not** run any of this (`RELEASING.md`). Releasing
from a red `main` publishes a red `main`.
