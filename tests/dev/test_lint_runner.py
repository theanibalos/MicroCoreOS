"""Tests for the unified architecture checker report and runner (Issue 53)."""

import json
from unittest.mock import patch
from microcoreos import cli
from microcoreos_dev.lint import (
    ALL_CHECKERS,
    format_json,
    format_text,
    run_checks,
)


def test_real_repo_check_is_clean():
    """CI gate: the real repo must pass all architecture checkers."""
    report = run_checks()
    assert report.success is True
    assert report.exit_code() == 0
    assert report.summary["errors"] == 0
    assert len(report.checkers) == len(ALL_CHECKERS)
    assert all(c.status in ("ok", "warning") for c in report.checkers)


def test_format_json_and_text():
    report = run_checks()
    text = format_text(report)
    assert "🔍 [MicroCoreOS] Integrity & Architecture Check" in text
    assert "PASSED" in text

    raw_json = format_json(report)
    parsed = json.loads(raw_json)
    assert parsed["success"] is True
    assert parsed["summary"]["errors"] == 0


def test_detects_discovery_naming_violation(tmp_path):
    tools_dir = tmp_path / "tools" / "payments"
    tools_dir.mkdir(parents=True)
    (tools_dir / "gateway.py").write_text(
        "from microcoreos import BaseTool\nclass PaymentGatewayTool(BaseTool):\n    pass\n",
        encoding="utf-8",
    )
    report = run_checks(root=str(tmp_path), checkers=["discovery_naming"])
    assert report.success is False
    assert report.exit_code() == 1
    assert any(f.code == "NAMING_MISNAMED_FILE" for f in report.findings)


def test_detects_domain_isolation_violation(tmp_path):
    p_dir = tmp_path / "domains" / "orders" / "plugins"
    p_dir.mkdir(parents=True)
    (p_dir / "checkout_plugin.py").write_text(
        "import domains.users\nclass CheckoutPlugin:\n    pass\n",
        encoding="utf-8",
    )
    report = run_checks(root=str(tmp_path), checkers=["domain_isolation"])
    assert report.success is False
    assert report.exit_code() == 1
    assert any(f.code == "ILLEGAL_CROSS_DOMAIN_IMPORT" for f in report.findings)


def test_detects_route_collision(tmp_path):
    p1 = tmp_path / "domains" / "orders" / "plugins"
    p1.mkdir(parents=True)
    (p1 / "list_orders_plugin.py").write_text(
        "class ListOrdersPlugin:\n"
        "    def on_boot(self):\n"
        "        self.http.add_endpoint('/orders', 'GET', self.list)\n",
        encoding="utf-8",
    )
    p2 = tmp_path / "domains" / "billing" / "plugins"
    p2.mkdir(parents=True)
    (p2 / "billing_orders_plugin.py").write_text(
        "class BillingOrdersPlugin:\n"
        "    def on_boot(self):\n"
        "        self.http.add_endpoint('/orders', 'GET', self.bills)\n",
        encoding="utf-8",
    )
    report = run_checks(root=str(tmp_path), checkers=["route_collisions"])
    assert report.success is False
    assert report.exit_code() == 1
    assert any(f.code == "ROUTE_COLLISION" for f in report.findings)


def test_detects_table_ownership_collision(tmp_path):
    m1 = tmp_path / "domains" / "users" / "migrations"
    m1.mkdir(parents=True)
    (m1 / "001_users.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")

    m2 = tmp_path / "domains" / "auth" / "migrations"
    m2.mkdir(parents=True)
    (m2 / "001_users.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")

    report = run_checks(root=str(tmp_path), checkers=["table_ownership"])
    assert report.success is False
    assert report.exit_code() == 1
    assert any(f.code == "TABLE_OWNERSHIP_COLLISION" for f in report.findings)


def test_strict_mode_escalates_warnings_to_failure(tmp_path):
    p_dir = tmp_path / "domains" / "users" / "plugins"
    p_dir.mkdir(parents=True)
    (p_dir / "p1_plugin.py").write_text(
        "from pydantic import BaseModel, Field\n"
        "class Req1(BaseModel):\n"
        "    name: str = Field(min_length=2)\n",
        encoding="utf-8",
    )
    (p_dir / "p2_plugin.py").write_text(
        "from pydantic import BaseModel, Field\n"
        "class Req2(BaseModel):\n"
        "    name: str = Field(min_length=5)\n",
        encoding="utf-8",
    )

    # Standard mode: warning does not fail
    report_std = run_checks(root=str(tmp_path), checkers=["field_divergence"], strict=False)
    assert report_std.success is True
    assert report_std.exit_code(strict=False) == 0
    assert report_std.summary["warnings"] == 1

    # Strict mode: warning fails
    report_strict = run_checks(root=str(tmp_path), checkers=["field_divergence"], strict=True)
    assert report_strict.success is False
    assert report_strict.exit_code(strict=True) == 1


def test_crashed_checker_reports_error_not_silent_empty():
    """A broken checker must report error status and an error finding, never silent success."""
    with patch.dict(ALL_CHECKERS, {"exploding": lambda root: 1 / 0}):
        report = run_checks(checkers=["exploding"])
        assert report.success is False
        assert report.exit_code() == 1
        exploding_status = next(s for s in report.checkers if s.name == "exploding")
        assert exploding_status.status == "error"
        assert "division by zero" in (exploding_status.error or "")


def test_cli_check_command(capsys):
    exit_code = cli.main(["check"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASSED" in out


def test_cli_check_json_format(capsys):
    exit_code = cli.main(["check", "--format=json"])
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert "checkers" in data
