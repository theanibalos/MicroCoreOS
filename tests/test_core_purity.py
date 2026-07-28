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

PACKAGE = Path(__file__).resolve().parent.parent / "microcoreos"

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

DISTRIBUTION_MODULES = ["cli.py", "catalog.py", "scaffold.py", "upgrade.py"]


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
            if r not in sys.stdlib_module_names and r != "microcoreos"
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
