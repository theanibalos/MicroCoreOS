from microcoreos_dev.lint.checkers.tables import check_table_ownership


def _scan(root="."):
    return [f.message for f in check_table_ownership(root=str(root))]


def _write_migration(root, domain, filename, sql):
    migrations = root / "domains" / domain / "migrations"
    migrations.mkdir(parents=True, exist_ok=True)
    (migrations / filename).write_text(sql, encoding="utf-8")


def test_real_repo_has_no_duplicate_tables():
    """CI gate: table ownership over the actual codebase must be clean.

    Runs the same scan the linter performs at boot (CREATE TABLE names across
    domains/*/migrations/*.sql) against the real domains/ tree. A duplicate
    table declared by more than one domain here fails the suite instead of
    only warning at boot.
    """
    assert _scan() == []


def test_detects_table_collision(tmp_path):
    ddl = "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);"
    _write_migration(tmp_path, "domain_a", "001_create_widgets.sql", ddl)
    _write_migration(tmp_path, "domain_b", "001_create_widgets.sql", ddl)

    warnings = _scan(tmp_path)

    assert len(warnings) == 1
    assert "widgets" in warnings[0]
    assert "domain_a" in warnings[0]
    assert "domain_b" in warnings[0]


def test_no_collision_between_different_tables(tmp_path):
    _write_migration(tmp_path, "domain_a", "001_create_widgets.sql",
                     "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY);")
    _write_migration(tmp_path, "domain_b", "001_create_gadgets.sql",
                     "CREATE TABLE IF NOT EXISTS gadgets (id INTEGER PRIMARY KEY);")

    assert _scan(tmp_path) == []
