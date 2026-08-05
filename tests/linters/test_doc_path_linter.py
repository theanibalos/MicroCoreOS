"""Dead references: prose naming a file that is not on disk."""

import pytest
from unittest.mock import MagicMock

from domains.devtools.plugins.doc_path_linter_plugin import DocPathLinterPlugin


def make_plugin():
    container = MagicMock()
    container.registry = MagicMock()
    return DocPathLinterPlugin(container=container, logger=MagicMock())


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_real_repo_has_no_dead_paths():
    """
    CI gate. This is the check's whole reason to exist: two folder
    reorganizations left 31 references pointing at files that had moved —
    including `.agent/workflows/new-tool.md` telling an agent the parity suite
    is mandatory and naming two files that were not there.
    """
    assert make_plugin().check(".") == []


def test_flags_a_path_that_does_not_exist(tmp_path):
    write(tmp_path, "docs/guide.md", "Read `tools/ghost/ghost_tool.py` before starting.")
    findings = make_plugin().check(str(tmp_path))
    assert len(findings) == 1
    assert "tools/ghost/ghost_tool.py" in findings[0]
    assert "docs/guide.md:1" in findings[0]


def test_names_the_new_location_when_the_file_merely_moved(tmp_path):
    write(tmp_path, "docs/guide.md", "See `tests/tools/test_state_parity.py`.")
    write(tmp_path, "tests/tools/state/test_state_parity.py", "")
    findings = make_plugin().check(str(tmp_path))
    assert "→ moved to tests/tools/state/test_state_parity.py" in findings[0]


def test_two_candidates_are_not_evidence_of_either(tmp_path):
    """An ambiguous basename gets the finding but no guess."""
    write(tmp_path, "docs/guide.md", "See `old/place/thing.py`.")
    write(tmp_path, "a/thing.py", "")
    write(tmp_path, "b/thing.py", "")
    findings = make_plugin().check(str(tmp_path))
    assert len(findings) == 1
    assert "moved to" not in findings[0]


def test_ignores_fenced_code_blocks(tmp_path):
    """A plan template names the files an executor must CREATE."""
    write(tmp_path, "docs/plan.md", "```yaml\ntest: tests/test_refund.py\n```\n")
    assert make_plugin().check(str(tmp_path)) == []


def test_a_bare_filename_is_a_name_not_a_location(tmp_path):
    write(tmp_path, "docs/guide.md", "As ELASTIC_DEPLOYMENT.md explains, ...")
    assert make_plugin().check(str(tmp_path)) == []


def test_markdown_links_resolve_from_their_own_page(tmp_path):
    write(tmp_path, "docs/index.md", "See [debt](internal/TECH_DEBT.md).")
    write(tmp_path, "docs/internal/TECH_DEBT.md", "")
    assert make_plugin().check(str(tmp_path)) == []


def test_placeholders_are_not_paths(tmp_path):
    write(tmp_path, "docs/guide.md", "Plugins live in `domains/{domain}/plugins/{feature}_plugin.py`.")
    assert make_plugin().check(str(tmp_path)) == []


def test_string_literals_in_code_are_not_references(tmp_path):
    """A test building a fixture names a file it is about to create."""
    write(tmp_path, "tests/test_thing.py", 'PATH = "domains/shop/plugins/list_orders_plugin.py"\n')
    assert make_plugin().check(str(tmp_path)) == []


def test_python_comments_and_docstrings_are_checked(tmp_path):
    write(tmp_path, "tools/thing.py", '"""See tools/gone/gone_tool.py."""\n\n# also tools/other/other_tool.py\n')
    findings = make_plugin().check(str(tmp_path))
    assert len(findings) == 2
    assert "tools/thing.py:1" in findings[0]
    assert "tools/thing.py:3" in findings[1]


def test_the_reported_line_is_the_source_line(tmp_path):
    """Docstring arithmetic reports a line off by one or two; this does not."""
    write(tmp_path, "tools/thing.py", '"""\nHeader.\n\nSee tools/gone/gone_tool.py here.\n"""\n')
    findings = make_plugin().check(str(tmp_path))
    assert "tools/thing.py:4" in findings[0]


def test_a_suppressed_line_is_not_a_finding(tmp_path):
    write(tmp_path, "docs/guide.md", "After `microcoreos add auth`: `tools/auth/auth_tool.py` <!-- lint:no-path -->")
    assert make_plugin().check(str(tmp_path)) == []


def test_historical_records_are_left_alone(tmp_path):
    """A changelog entry naming the path that was right then is accurate."""
    write(tmp_path, "ROADMAP.md", "Fixed in `tools/gone/gone_tool.py`.")
    write(tmp_path, "docs/internal/TECH_DEBT.md", "Was `tools/gone/gone_tool.py`.")
    assert make_plugin().check(str(tmp_path)) == []


@pytest.mark.anyio
async def test_on_boot_registers_findings():
    plugin = make_plugin()
    plugin.check = lambda *a, **k: ["docs/x.md:1 cites 'a/b.py', which does not exist"]
    await plugin.on_boot()
    plugin.registry.register_domain_metadata.assert_called_once()
    domain, key, value = plugin.registry.register_domain_metadata.call_args[0]
    assert (domain, key) == ("devtools", "dead_path_warnings")
    assert len(value) == 1


@pytest.mark.anyio
async def test_on_boot_registers_nothing_when_clean():
    plugin = make_plugin()
    plugin.check = lambda *a, **k: []
    await plugin.on_boot()
    plugin.registry.register_domain_metadata.assert_not_called()
