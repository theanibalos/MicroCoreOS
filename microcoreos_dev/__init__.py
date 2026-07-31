"""MicroCoreOS development tooling — the half that never runs in production.

The plan pipeline (`status`, `plan validate`, `plan probe`, `migrate`,
`schema`) is what you run AT a project while building it, never code a booted
application imports. That is what makes it a dev dependency: `uv sync --no-dev`
leaves it out of the deploy.

The dependency runs one way and only one: this package imports `microcoreos`,
`microcoreos` never imports this. `tests/test_core_purity.py` enforces it, and
docs/DEV_PACKAGE_SPLIT.md is why.
"""
