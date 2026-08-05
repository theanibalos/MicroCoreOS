# PLAN — `microcoreos-dev`, the development package

> **Status: NOT STARTED.** This is the plan `docs/internal/TECH_DEBT.md` item 9 asks for
> ("a package split is the kind of change that wants its own plan"). Item 9 has
> the measurements and the symptom; this doc has the cut.

## The model: `devDependencies`

Svelte and Vue draw a line this project does not. `vue` is a dependency; `vite`
and `svelte-check` are devDependencies. `npm ci --omit=dev` and the tooling is
gone from the deploy. Nobody had to write a version-tolerance shim for vite,
and the reason is one row of the table below:

| Svelte/Vue | MicroCoreOS today | After |
|---|---|---|
| `vue` in `dependencies` | the `microcoreos` wheel | unchanged |
| `vite` / `svelte-check` in `devDependencies` | `plan_validator_plugin.py` **copied into your source** | the `microcoreos-dev` wheel in `[dependency-groups] dev` |
| `npm ci --omit=dev` | `uv sync --no-dev` — already in `Dockerfile:22` | unchanged, but it finally bites |
| vite is never copied into `src/` | `domains/devtools` is materialized as your source | stops being materialized |

The last row is the whole thing. The inverted dependency item 9 describes —
`microcoreos/pipeline.py` importing `domains.devtools.plugins.plan_validator_plugin`,
the wheel importing the user's vendored copy — **is** the absence of that row.
`_plan_attr` is what a framework has to write when it depends on a vendored
copy of itself that may be any number of releases old.

The deploy mechanism is already in place and already correct. `uv sync --no-dev`
runs at `Dockerfile:22`. It does not exclude the validator because the validator
is not a dependency: it is source, and `COPY . .` at line 25 puts it in the
image, where the Kernel discovers it and boots it. Nothing about the container
needs to change — the code has to move to where `--no-dev` can see it.

## Where it lives: same repo, two distributions

A uv workspace: the root stays the `microcoreos` project, `microcoreos-dev/`
becomes a member with its own `pyproject.toml`. This is the Vue core monorepo
shape — several published packages, one version number, one release.

A separate repo was considered and rejected. Two repos reintroduce version skew
at the distribution level, which is precisely what `_plan_attr` papers over
today. The point of this split is to delete that shim, not to relocate the
condition that requires it.

An extra (`microcoreos[dev]`) does not work: extras add dependencies, they
cannot remove modules from a wheel.

---

## Phase 0 — the code cut (packaging untouched)

Goal: the dependency runs one way. Everything downstream is a consequence. The
suite must be green at the end of this phase without `pyproject.toml` being
touched, which makes the phase reversible on its own.

```
microcoreos_dev/
  plan/schema.py    ← validator 29-238    Plan, PlanFeature, unknown_plan_keys
  plan/scan.py      ← validator 239-430   LiveSnapshot, scan_live_*, offline_snapshot
  plan/rules.py     ← validator 432-1223  PlanValidator, run_validation, validate_yaml
  pipeline.py       ← microcoreos/pipeline.py 1-527    migrate, schema, status
  probe.py          ← microcoreos/pipeline.py 528-785
  cli.py
```

This is where the validator's internal cut gets decided, and it is why the
split comes first: `domains/devtools/models/` stops being a possible
destination for the plan schema the moment the file leaves the project.

1. **Move the six files.** `microcoreos/pipeline.py` ceases to exist.
2. **Delete `_plan_attr`** (`pipeline.py:589`) and read the attributes directly.
   `test_probe_survives_a_project_whose_validator_predates_this_command`
   (`test_cli.py:724`) goes with it — it exists only to cover the shim, and
   keeping it would mean keeping the shim it covers.
3. **Delete `PlanValidatorPlugin` and `POST /system/plan/validate`.** The only
   thing the endpoint sees that the offline path does not is *live
   subscribers*, an asymmetry `pipeline.py:348` already prints as a known
   limitation. If anyone misses it, the answer is a `--live` flag that boots
   the app itself, not an endpoint next to the business.
4. **Rewrite `dev_infra/plan_fuzzer.py`.** It is a real consumer of the endpoint
   (`URL = "http://localhost:5000/system/plan/validate"`, line 31). Calling
   `validate_yaml` in-process drops the server requirement and makes it faster;
   it then moves into the dev package with the validator.

## Phase 1 — the distribution boundary

5. **uv workspace**: root plus `microcoreos-dev/`. This is the structural cost
   of the phase and there is no cheaper form of it.
6. **`scaffold.PYPROJECT_TEMPLATE`**: add `"microcoreos-dev"` to
   `[dependency-groups] dev`. That single line is the entire devDependencies
   analogy, expressed in the file every new project gets.
7. **`hatch_build.py` needs no change.** `RUNTIME_ENTRIES` lists
   `"domains/devtools"` as a directory; the file is deleted, so the wheel
   payload adjusts on its own. The linters stay where they are.
8. **The commands keep their names.** `microcoreos plan validate` continues to
   work by lazily importing `microcoreos_dev` and printing an install line if
   it is absent. Eight docs, four workflows and `AGENTS.md` name the current
   form, and agents read those files as instructions — renaming the commands
   means rewriting that corpus for no gain.

## Phase 2 — migration path and the doc tail

9. **Existing materialized projects.** `upgrade.py` sees the validator as
   `gone` (deletable if untouched, `gone_yours` if edited). The plausibility
   guardrail at `upgrade.py:488` holds for a single withdrawn file — that needs
   a test rather than an assumption. It also needs a note: once the file is
   gone, `plan validate` stops working until the dev dependency is added.
10. **Tests.** `test_plan_validator.py` (1292 lines) and `tests/corpus/` move
    next to the dev package; roughly fifteen pipeline tests leave
    `test_cli.py`.
11. **`test_core_purity.py` gains the rule that replaces the inversion**: no
    module under `microcoreos/` imports `microcoreos_dev` at module level (the
    delegation in step 8 lives inside a function). That file already draws the
    kernel/distribution line and already classifies `pipeline.py` as
    distribution — this extends the same test to the boundary that actually
    broke. The inversion becomes a CI failure instead of something discovered
    by restoring an old commit and watching `plan probe` raise `AttributeError`.
12. **Docs.** Nine sites name the endpoint; `docs/CLI.md:34` lists what gets
    materialized; `plans/README.md:111,266` give the curl form. `AI_CONTEXT.md`
    regenerates itself at boot and is never edited by hand.

## Verification

Build the image and assert two things: `microcoreos_dev` is not in
site-packages, and `/app/domains/devtools/plugins/plan_validator_plugin.py`
does not exist. That is "gone at deploy" turned into a check rather than a
claim.

---

## Phase 3 — the linters

Settled by the project's own rule: **anything that is not the framework leaves.**
The linters are a CI gate (`ci.yml:186-194` boots the app and curls
`GET /system/lint`), so they go, `domains/devtools/` stops being materialized,
and `RUNTIME_ENTRIES` loses the entry.

**`RUNTIME_ENTRIES` cannot go first.** Dropping `domains/devtools` before the
linters have somewhere to live does not clean anything up — it deletes a
capability from every new project. Three couplings have to be undone first:

- the seven linters lint the USER's domains. With none materialized, a project
  gets no architecture checking at all, and nothing tells its author
- `EventContractLinterPlugin` owns `GET /system/lint` itself (`get_lint`,
  line 406): it is the aggregator that reads all six linters' findings back out
  of the registry
- `EventSchemasPlugin` is genuine runtime — it serves
  `GET /system/events/schemas`, the seed of a schema registry — and it is built
  from metadata `EventContractLinterPlugin` registers at boot. Runtime code
  depending on a linter is its own knot, and it has to be untied before either
  one can move

So the order is: `microcoreos-dev lint` first (the five disk-only linters), then
decide the aggregator, `event_contract` and `tool_doc_drift`, then
`RUNTIME_ENTRIES` last. Doing it in the other order is how a cleanup becomes an
outage.

Item 9 recorded them as needing the live boot. Measured, that is true of one:

| linter | reads live state? |
|---|---|
| `discovery_naming`, `domain_isolation`, `field_divergence`, `route_collision`, `table_ownership` | **no** — AST scans of `domains/` via `iter_plugin_files()` |
| `event_contract` | one `registry.get_domain_metadata()` site — needs its own look |
| `tool_doc_drift` | **yes** — compares each tool's docstring to the live instance |

The registry is where five of them PUBLISH findings, not where they get their
input. So `microcoreos-dev lint` is mostly the same move `plan validate`
already made: read the disk, exit with a status code, no server. CI drops the
boot and the curl for that part.

`tool_doc_drift` is the one that genuinely needs a booted container, and it
should be decided on its own rather than dragging a boot into a command that
five sevenths of does not need one.

`event_schemas_plugin.py` (94 lines) is genuine runtime and stays.
