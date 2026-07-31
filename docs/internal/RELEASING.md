# Releasing

The whole release is one tag. Everything else is automated in
[`.github/workflows/release.yml`](../.github/workflows/release.yml).

```bash
# 1. Bump the version — this is the only file that carries it
$EDITOR pyproject.toml          # version = "0.1.1"

# 2. Commit it and let CI go green on main. Do not skip this:
#    the release workflow does NOT run the test suite.
git commit -am "Release 0.1.1" && git push

# 3. Tag and push the tag. That is the release.
git tag -a v0.1.1 -m "MicroCoreOS 0.1.1"
git push origin v0.1.1
```

The tag triggers the workflow. It verifies the tag matches `pyproject.toml`,
builds the wheel and sdist, installs the wheel in a clean venv and checks that
`microcoreos new` scaffolds a correct project — auth available but not
installed, `logout` present, the CRUD half absent — and only then publishes.

There is **no API token anywhere.** PyPI trusts a short-lived OIDC token GitHub
mints for this workflow, in this repository, in the `pypi` environment. That is
what the three fields registered on PyPI mean, and why a run from anywhere else
cannot publish.

## Version numbers

`MAJOR.MINOR.PATCH`, and the only one that carries a promise is MAJOR.

| Bump | When |
|---|---|
| PATCH `0.1.1` | A fix. Nothing about the contract changes |
| MINOR `0.2.0` | Something new. Everything that worked still works |
| MAJOR `1.0.0` | You broke the compatibility surface below |

Pre-1.0 the convention is that breaking changes may ride in MINOR. That is a
convention, not permission: someone already has `uv add microcoreos` in a
project.

**The compatibility surface** (frozen since 0.1.0, see
[TECH_DEBT.md](TECH_DEBT.md) item 7):

- The five names re-exported from `microcoreos/__init__.py`
- The extra names: `auth`, `kafka`, `postgres`, `rabbitmq`, `redis`, `s3`,
  `scheduler`, `all`
- The `.microcoreos/manifest.json` format

## Rehearsing

Before anything unusual — a new extra name, a change to the workflow, a first
release after a long gap — rehearse against TestPyPI. It is a separate site
with a separate account and its own trusted publisher, registered with
environment `testpypi`.

```
Actions → Release → Run workflow → target: testpypi
```

Installing from there needs both indexes, because TestPyPI does not host your
dependencies:

```bash
uv pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ 'microcoreos[auth]'
```

## When it fails

**The publish job failed.** Look at *where*. Reaching `upload.pypi.org` is
infrastructure — it timed out once on the 0.1.0 release and a re-run fixed it:

```bash
gh run rerun <run-id> --failed
```

A rejected OIDC token is configuration: the environment name in the workflow
must match the one registered on PyPI exactly.

**Either way, if publish failed, nothing was uploaded** — check
`https://pypi.org/pypi/microcoreos/json` and re-run. The version is not spent.

**You tagged the wrong commit or the wrong number.** The tag check catches a
mismatch before anything is built. Fix it by deleting and re-tagging:

```bash
git tag -d v0.1.1
git push --delete origin v0.1.1
```

**You published something broken.** This is the one that does not undo. A
version number on PyPI can never be reused, even after deleting the files.
What you can do is **yank** it: it stays installable for anyone who pinned
`==0.1.1`, but resolvers stop choosing it for new installs. Then publish the
fix as `0.1.2`.

## What the release does NOT do

- **It does not run the tests.** CI does, on push. Releasing from a red `main`
  publishes a red `main`.
- **It does not update the README, the changelog or the GitHub Release.** The
  Release page is created by hand (`gh release create v0.1.1 --notes-file ...`)
  and is independent of PyPI — publishing works without one.
- **It does not ship the tests.** `tests/` is in neither the wheel nor the
  scaffolded project. Nobody who installs the package runs them; what covers
  the artefact they download is the `packaged-e2e` job in CI.
