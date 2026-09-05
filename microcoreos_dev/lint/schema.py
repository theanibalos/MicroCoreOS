"""Structured report and findings contract for MicroCoreOS architecture checkers.

Issue 53: Unified checker report, application-owned CI policy.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class CheckFinding(BaseModel):
    """A single diagnostic finding from a checker."""
    checker: str
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    waived: bool = False
    waiver_reason: Optional[str] = None


class CheckerStatus(BaseModel):
    """Execution status and duration for one checker."""
    name: str
    status: Literal["ok", "warning", "error", "skipped"]
    duration_ms: float = 0.0
    findings_count: int = 0
    error: Optional[str] = None


class CheckReport(BaseModel):
    """Unified report containing all executed checkers and findings."""
    success: bool
    checkers: list[CheckerStatus] = Field(default_factory=list)
    findings: list[CheckFinding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    duration_ms: float = 0.0

    def exit_code(self, strict: bool = False) -> int:
        """Calculate the process exit code.

        Default policy:
          - 0 if no errors (warnings and info are non-blocking).
          - 1 if any error exists.

        Strict policy (--strict):
          - 1 if any error OR warning exists.
        """
        errors = self.summary.get("errors", 0)
        warnings = self.summary.get("warnings", 0)
        if strict and (errors > 0 or warnings > 0):
            return 1
        return 1 if errors > 0 else 0
