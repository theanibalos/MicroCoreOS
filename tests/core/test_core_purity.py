"""
The claim on the README's front page, made checkable.

`microcoreos/` holds two things that happen to share a folder: the KERNEL a
running app depends on, and the DISTRIBUTION code behind the `microcoreos`
command. They never mix — booting an app imports the first set and none of the
second — but nothing enforced that, so the boundary could erode without anyone
noticing and the "pure stdlib" claim would quietly become false.

These tests are what make the number on the README a fact rather than a memory.
"""

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent.parent / "microcoreos"

# What a running application depends on. Everything else in the package is the
# CLI: scaffolding a project, installing an extra, upgrading — build-time work
# that never executes inside your app.
KERNEL_MODULES = [
    "__init__.py",
    "base_plugin.py",
    "base_tool.py",
    "context.py",
    "container.py",
    "kernel.py",
    "registry.py",
]

# `project.py` is distribution: locating the project a command is being run AT,
# and the seam `microcoreos-dev` is allowed to use. The plan pipeline used to be
# here too, as `pipeline.py`; it now ships as its own package — see
# docs/internal/DEV_PACKAGE_SPLIT.md and the two direction tests at the bottom of this
# file, which are what keep it from coming back.
DISTRIBUTION_MODULES = ["cli.py", "catalog.py", "scaffold.py", "upgrade.py",
                        "project.py"]


def _imported_roots(path: Path) -> set[str]:
    """Top-level module name of every import in a file, without executing it."""
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_kernel_is_stdlib_only():
    """
    "Pure stdlib. No external dependencies in core." A third-party import here
    is not a style problem: it is a dependency every user of the framework
    inherits forever, for code that runs in every request.
    """
    offenders = {}
    for name in KERNEL_MODULES:
        foreign = {
            r for r in _imported_roots(PACKAGE / name)
            if r not in sys.stdlib_module_names and r not in ("microcoreos", "mutmut")
        }
        if foreign:
            offenders[name] = sorted(foreign)

    assert not offenders, f"the kernel grew third-party imports: {offenders}"


def test_the_kernel_does_not_import_the_distribution_half():
    """
    The dependency runs one way: `cli` imports `kernel`, never the reverse.
    Reversing it would drag the scaffolder, the extras catalog and `dotenv`
    into every booted app — and would make the line count on the README a
    fiction, since all of it would then be code your app depends on.
    """
    distribution = {m[:-3] for m in DISTRIBUTION_MODULES}
    for name in KERNEL_MODULES:
        source = (PACKAGE / name).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module and module.startswith("microcoreos."):
                target = module.split(".")[1]
                assert target not in distribution, (
                    f"{name} imports microcoreos.{target}, which is distribution "
                    f"code — the kernel must not depend on the CLI half"
                )


def test_every_module_is_on_one_side_or_the_other():
    """A new file in the package belongs to one half or the other, and the
    person adding it decides which — not a later reader guessing."""
    on_disk = {p.name for p in PACKAGE.glob("*.py")}
    accounted = set(KERNEL_MODULES) | set(DISTRIBUTION_MODULES)
    assert on_disk == accounted, (
        "microcoreos/ has modules this test does not classify: "
        f"{sorted(on_disk - accounted)}. Add it to KERNEL_MODULES (and it must "
        "then pass the stdlib rule) or to DISTRIBUTION_MODULES."
    )


# ── The direction between the two packages ─────────────────────────────────
#
# The tests above police one boundary INSIDE the wheel. These two police the
# boundary BETWEEN the wheel and `microcoreos-dev`, which is the one that
# actually broke: `pipeline.py` shipped in the wheel and imported
# `domains.devtools.plugins.plan_validator_plugin` — the user's VENDORED source,
# so the framework depended on the project. Restoring a project to an earlier
# commit was enough to kill `microcoreos plan probe` with AttributeError, twice
# in a row, and what got written was a version-tolerance shim (`_plan_attr`)
# rather than the direction being fixed. Nothing was watching, because nothing
# could: the two halves were not distinguishable to a test.

DEV_PACKAGE = Path(__file__).resolve().parent.parent.parent / "microcoreos_dev"


def _module_level_imports(path: Path) -> set[str]:
    """Top-level module name of every import that runs AT IMPORT TIME.

    Imports nested in a function body are excluded on purpose: they are the
    sanctioned way to reach for something optional, and the whole delegation in
    `cli.py` depends on being allowed to do exactly that.
    """
    roots: set[str] = set()

    def walk(node, in_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            nested = in_function or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if not nested:
                if isinstance(child, ast.Import):
                    roots.update(a.name.split(".")[0] for a in child.names)
                elif (isinstance(child, ast.ImportFrom)
                      and child.level == 0 and child.module):
                    roots.add(child.module.split(".")[0])
            walk(child, nested)

    walk(ast.parse(path.read_text(encoding="utf-8")), False)
    return roots


def test_the_framework_does_not_import_the_development_package():
    """
    `microcoreos-dev` depends on `microcoreos`. Never the reverse.

    `cli.py` IS allowed to reach for `microcoreos_dev` — that is how
    `microcoreos plan validate` keeps working under the name every doc and
    workflow uses — but only from inside the function that runs the command. At
    module level it would make the framework require its own development tooling
    in order to import, so a production install with `uv sync --no-dev` would
    fail to boot at all.
    """
    for path in sorted(PACKAGE.glob("*.py")):
        assert "microcoreos_dev" not in _module_level_imports(path), (
            f"{path.name} imports microcoreos_dev at module level. The framework "
            f"must not depend on the development package — move the import "
            f"inside the function that needs it."
        )


def test_neither_package_imports_the_user_s_own_source():
    """
    `domains/` and `tools/` are the USER's files, materialized into their
    project and edited by them. Either package importing one statically is the
    inversion this split removed: code that ships in a wheel, binding itself to
    a vendored copy it does not version.

    Dynamic loading is untouched and is not what this checks — `plan probe`
    imports the plugin under test by name, and that is its entire job.
    """
    for package in (PACKAGE, DEV_PACKAGE):
        for path in sorted(package.rglob("*.py")):
            imported = _module_level_imports(path)
            assert not imported & {"domains", "tools"}, (
                f"{path.relative_to(package.parent)} imports "
                f"{sorted(imported & {'domains', 'tools'})} — that is the "
                f"project's own vendored source, and a package must never "
                f"depend on it."
            )
