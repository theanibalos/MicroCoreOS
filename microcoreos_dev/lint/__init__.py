"""Unified architecture checkers and report runner.

Issue 53: Unified checker report, application-owned CI policy.
"""

from microcoreos_dev.lint.schema import CheckFinding, CheckerStatus, CheckReport
from microcoreos_dev.lint.runner import ALL_CHECKERS, run_checks
from microcoreos_dev.lint.report import format_json, format_text

__all__ = [
    "ALL_CHECKERS",
    "CheckFinding",
    "CheckerStatus",
    "CheckReport",
    "format_json",
    "format_text",
    "run_checks",
]
