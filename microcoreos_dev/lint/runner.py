"""Orchestrator for MicroCoreOS architecture checkers.

Issue 53: Unified checker report, application-owned CI policy.
"""

import time
from typing import Callable, Optional
from microcoreos_dev.lint.schema import CheckFinding, CheckerStatus, CheckReport
from microcoreos_dev.lint.checkers.naming import check_discovery_naming
from microcoreos_dev.lint.checkers.isolation import check_domain_isolation
from microcoreos_dev.lint.checkers.events import check_event_contracts
from microcoreos_dev.lint.checkers.divergence import check_field_divergence
from microcoreos_dev.lint.checkers.routes import check_route_collisions
from microcoreos_dev.lint.checkers.tables import check_table_ownership
from microcoreos_dev.lint.checkers.doc_drift import check_tool_doc_drift

# The complete list of standard checkers
ALL_CHECKERS: dict[str, Callable] = {
    "discovery_naming": lambda root: check_discovery_naming(root=root),
    "domain_isolation": lambda root: check_domain_isolation(root=root),
    "event_contracts": lambda root: check_event_contracts(root=root)[0],
    "field_divergence": lambda root: check_field_divergence(root=root),
    "route_collisions": lambda root: check_route_collisions(root=root),
    "table_ownership": lambda root: check_table_ownership(root=root),
    "tool_doc_drift": lambda root: check_tool_doc_drift(root=root),
}


def run_checks(
    root: str = ".",
    checkers: Optional[list[str]] = None,
    strict: bool = False,
) -> CheckReport:
    """Run specified or all checkers and return a unified CheckReport.

    Guarantee: If a checker fails to execute or is missing, it is reported as
    status="error" and produces an error finding, never a silent pass.
    """
    total_start = time.perf_counter()

    to_run = checkers if checkers is not None else list(ALL_CHECKERS.keys())
    statuses: list[CheckerStatus] = []
    all_findings: list[CheckFinding] = []

    for name in to_run:
        checker_fn = ALL_CHECKERS.get(name)
        if checker_fn is None:
            # Unknown / missing checker requested
            status = CheckerStatus(
                name=name,
                status="error",
                duration_ms=0.0,
                findings_count=1,
                error=f"Unknown checker '{name}'. Available: {list(ALL_CHECKERS.keys())}",
            )
            statuses.append(status)
            all_findings.append(
                CheckFinding(
                    checker=name,
                    code="UNKNOWN_CHECKER",
                    severity="error",
                    message=status.error or "",
                )
            )
            continue

        start_t = time.perf_counter()
        try:
            findings = checker_fn(root)
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)

            has_error = any(f.severity == "error" for f in findings)
            has_warning = any(f.severity == "warning" for f in findings)

            if has_error:
                ch_status = "error"
            elif has_warning:
                ch_status = "warning"
            else:
                ch_status = "ok"

            statuses.append(
                CheckerStatus(
                    name=name,
                    status=ch_status,
                    duration_ms=elapsed_ms,
                    findings_count=len(findings),
                )
            )
            all_findings.extend(findings)

        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
            statuses.append(
                CheckerStatus(
                    name=name,
                    status="error",
                    duration_ms=elapsed_ms,
                    findings_count=1,
                    error=str(e),
                )
            )
            all_findings.append(
                CheckFinding(
                    checker=name,
                    code="CHECKER_EXECUTION_ERROR",
                    severity="error",
                    message=f"Checker '{name}' crashed: {e}",
                )
            )

    total_duration_ms = round((time.perf_counter() - total_start) * 1000, 2)

    errors_count = sum(1 for f in all_findings if f.severity == "error")
    warnings_count = sum(1 for f in all_findings if f.severity == "warning")
    info_count = sum(1 for f in all_findings if f.severity == "info")

    summary = {
        "errors": errors_count,
        "warnings": warnings_count,
        "info": info_count,
        "total": len(all_findings),
        "checkers_run": len(statuses),
    }

    success = (errors_count == 0) if not strict else (errors_count == 0 and warnings_count == 0)

    return CheckReport(
        success=success,
        checkers=statuses,
        findings=all_findings,
        summary=summary,
        duration_ms=total_duration_ms,
    )
