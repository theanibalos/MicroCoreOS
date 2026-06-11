import pytest
from tools.sqlite.sqlite_tool import SqliteTool

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    tool = SqliteTool()
    await tool.setup()
    yield tool
    await tool.shutdown()

async def test_migration_topological_sort_intent(db, tmp_path, monkeypatch):
    """
    The intent is that migrations run in the order of their declared
    dependencies, not just by filename.

    Scenario:
    002_profiles depends on 001_users.
    Alphabetical execution would work, but when we force a crossed or
    inverted dependency, topological order must prevail.
    """
    # Build a domains structure inside a temporary directory
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    
    # Domain A: users (no dependencies)
    users_dir = domains_dir / "users" / "migrations"
    users_dir.mkdir(parents=True)
    (users_dir / "001_create_users.sql").write_text("CREATE TABLE users (id int);")
    
    # Domain B: profiles (depends on users)
    profiles_dir = domains_dir / "profiles" / "migrations"
    profiles_dir.mkdir(parents=True)
    # Note the 000 prefix: alphabetically it goes first, but the dependency moves it last
    (profiles_dir / "000_create_profiles.sql").write_text(
        "-- depends: users/001_create_users.sql\n"
        "CREATE TABLE profiles (user_id int, FOREIGN KEY(user_id) REFERENCES users(id));"
    )
    
    # Change into the temp directory so the tool finds 'domains/'
    monkeypatch.chdir(tmp_path)
    
    # Run boot (which applies migrations)
    await db.on_boot_complete(None)
    
    # Verify BOTH tables exist (if ordering failed, the profiles FK would error because users would not exist)
    tables = await db.query("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [t["name"] for t in tables]
    
    assert "users" in table_names
    assert "profiles" in table_names
    
    # Check the migration history for the actual application order
    history = await db.query("SELECT filename FROM _migrations_history ORDER BY id ASC")
    order = [h["filename"] for h in history]
    
    # The intent is that 001_create_users ran BEFORE 000_create_profiles
    assert order == ["001_create_users.sql", "000_create_profiles.sql"]

async def test_db_auto_migrate_false_skips_migrations(db, tmp_path, monkeypatch):
    """
    Issue 20: with DB_AUTO_MIGRATE=false (production replicas) boot does NOT
    run migrations. Migrating from production replicas is PROHIBITED: only
    the CI/CD pipeline migrates, under explicit human supervision, in a
    SINGLE instance: `DB_AUTO_MIGRATE=true main.py --boot-tool db`.
    """
    domains_dir = tmp_path / "domains"
    users_dir = domains_dir / "users" / "migrations"
    users_dir.mkdir(parents=True)
    (users_dir / "001_create_users.sql").write_text("CREATE TABLE users (id int);")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_AUTO_MIGRATE", "false")

    await db.on_boot_complete(None)

    tables = await db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    assert tables == []


async def test_migration_transaction_safety_intent(db, tmp_path, monkeypatch):
    """
    The intent is that each migration file is atomic. If one statement
    fails, NOTHING from that file may remain in the database or the history.
    """
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    
    blog_dir = domains_dir / "blog" / "migrations"
    blog_dir.mkdir(parents=True)
    # This migration creates a table and then fails
    (blog_dir / "001_fail.sql").write_text(
        "CREATE TABLE blog_posts (id int);\n"
        "INVALID SQL STATEMENT;"
    )
    
    monkeypatch.chdir(tmp_path)
    
    with pytest.raises(Exception):
        await db.on_boot_complete(None)
        
    # The blog_posts table must NOT exist (rollback)
    tables = await db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='blog_posts'")
    assert len(tables) == 0
    
    # No trace may remain in the history
    history = await db.query("SELECT * FROM _migrations_history WHERE domain='blog'")
    assert len(history) == 0
