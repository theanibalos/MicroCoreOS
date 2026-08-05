"""Dead references: a doc or docstring naming a file that is not there.

One of the linters reported by GET /system/lint.

Registry key: devtools/dead_path_warnings.

An instruction that names a file the project does not have is an instruction
to go wandering: the agent either invents what the file would have said or
goes looking for it in another checkout. The reference does not have to be
wrong when written — it goes dead when someone moves a folder, and nothing
else in the toolchain compares prose against disk.
"""

import ast
import io
import os
import re
import tokenize
from microcoreos import BasePlugin


# A path claim, not a name. Two deliberate narrowings:
#
#   - at least one "/" — `ELASTIC_DEPLOYMENT.md` in a sentence names a document,
#     `docs/ELASTIC_DEPLOYMENT.md` asserts where it lives. Only the second can
#     be wrong about the filesystem, and only the second is worth a warning.
#   - a known source extension — a bare dotted word is usually a module or a
#     domain, not a file.
#
# The trailing lookahead rejects word characters and "/" but NOT "." — a path
# that ends a sentence is the common case in prose, and `(?![\w/.-])` skips
# every one of them while still rejecting `thing.pyc`.
_PATH_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+\.(?:py|md|sql|yaml|yml|toml))(?![\w/])")

# A fenced code block is where the plan templates put their worked examples,
# and those name files on purpose that do not exist yet (`tests/test_refund.py`  lint:no-path
# is what the executor is being told to CREATE). Prose is where a reference
# claims something already exists, so prose is what gets checked.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Files whose job is to record history: a changelog entry naming the path that
# was correct at the time is accurate, and "fixing" it would falsify the record.
_HISTORICAL = ("ROADMAP.md", "docs/internal/")

# Never scanned: not ours, or generated.
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "htmlcov",
              "dist", "build", "mutants", ".pytest_cache", ".ruff_cache"}

# Paths cited to say they do NOT work. Naming them is the point of the
# sentence, so they are not findings.
_COUNTEREXAMPLES = {
    "plans/my_feature.yaml",
    "plans/twitter_plan.yaml",
}

# Opt out one line, in either syntax. For the legitimate cases: a path that is
# correct only after `microcoreos add`, an illustrative path in an error
# message, a replacement tool nobody has written yet. Suppressing is a
# decision, so it is written down where the reader can see it.
_SUPPRESS = ("lint:no-path", "<!-- lint:no-path -->")


class DocPathLinterPlugin(BasePlugin):
    """
    Scans prose (Markdown outside code fences, and Python comments/docstrings)
    for repo-relative file paths, and warns when the named file is not on disk.

    Reports the likely replacement when a file with the same basename exists
    somewhere else — which is the shape this failure almost always takes, a
    folder reorganized without propagating the references to it.
    """

    def __init__(self, container, logger):
        self.registry = container.registry
        self.logger = logger

    async def on_boot(self):
        warnings = self.check()
        if warnings:
            self.registry.register_domain_metadata("devtools", "dead_path_warnings", warnings)
            for w in warnings:
                self.logger.warning(f"[DocPathLinter] {w}")
        else:
            self.logger.info("[DocPathLinter] Documented paths verified. No dead references found.")

    # ── The check, usable without a booted system ─────────────────────────

    def check(self, root: str = ".") -> list[str]:
        root = os.path.abspath(root)
        index = self._basename_index(root)

        findings = []
        for path in self._scan_targets(root):
            rel = os.path.relpath(path, root)
            if rel.startswith(_HISTORICAL) or rel.replace(os.sep, "/").startswith(_HISTORICAL):
                continue
            for line_no, cited, line in self._cited_paths(path):
                if cited in _COUNTEREXAMPLES or "{" in cited or "<" in cited:
                    continue
                if any(marker in line for marker in _SUPPRESS):
                    continue
                # Resolve from the repo root AND from the citing file's own
                # directory: a Markdown link is relative to its page, so
                # `internal/TECH_DEBT.md` inside docs/ is correct as written.  lint:no-path
                here = os.path.dirname(path)
                if os.path.exists(os.path.join(root, cited)) or os.path.exists(os.path.join(here, cited)):
                    continue
                moved = index.get(os.path.basename(cited))
                hint = f" → moved to {moved}" if moved and moved != cited else ""
                findings.append(f"{rel}:{line_no} cites '{cited}', which does not exist{hint}")
        return findings

    # ── Internals ─────────────────────────────────────────────────────────

    def _scan_targets(self, root: str):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in sorted(filenames):
                if name.endswith((".md", ".py")):
                    yield os.path.join(dirpath, name)

    def _basename_index(self, root: str) -> dict:
        """basename → its single relative path. Ambiguous names are dropped:
        two candidates are not evidence of where a reference meant to point."""
        seen: dict[str, str | None] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
                seen[name] = None if name in seen else rel
        return {k: v for k, v in seen.items() if v}

    def _cited_paths(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            self.logger.warning(f"[DocPathLinter] Could not read {path}: {e}")
            return

        prose = self._python_prose(path, source) if path.endswith(".py") else self._markdown_prose(source)
        for line_no, text in prose:
            for match in _PATH_RE.finditer(text):
                yield line_no, match.group(1), text

    def _markdown_prose(self, source: str):
        in_fence = False
        for line_no, line in enumerate(source.splitlines(), start=1):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if not in_fence:
                yield line_no, line

    def _python_prose(self, path: str, source: str):
        """
        Comments and docstrings only — never a string literal in code.

        A test that writes a plugin path into a tmp_path is naming a file it is
        about to create, not claiming one exists. Reading those as references
        buries the real findings: on this repo they were 9 out of every 10.

        Works by marking which LINES are prose and then reading those lines
        out of the source, rather than reading the docstring's own text: a
        docstring's value is not its source lines (the opening quotes, any
        indentation), so arithmetic on it reports a line number off by one or
        two — and a linter whose file:line is approximate is one nobody trusts.
        """
        prose_lines = set()

        try:
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.COMMENT:
                    prose_lines.add(token.start[0])
        except (tokenize.TokenError, IndentationError, SyntaxError) as e:
            self.logger.warning(f"[DocPathLinter] Could not tokenize {path}: {e}")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.logger.warning(f"[DocPathLinter] Could not parse {path}: {e}")
            return
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not ast.get_docstring(node, clean=False):
                continue
            expr = node.body[0]
            prose_lines.update(range(expr.lineno, (expr.end_lineno or expr.lineno) + 1))

        for line_no, line in enumerate(source.splitlines(), start=1):
            if line_no in prose_lines:
                yield line_no, line
