"""Formatters for unified checker reports (text with emojis and json).

Issue 53: Unified checker report, application-owned CI policy.
"""

from collections import defaultdict
from microcoreos_dev.lint.schema import CheckReport


def format_json(report: CheckReport) -> str:
    """Format the report as formatted JSON."""
    return report.model_dump_json(indent=2)


def format_text(report: CheckReport) -> str:
    """Format the report as clean terminal text with emojis and clear diagnostics."""
    lines: list[str] = [
        "🔍 [MicroCoreOS] Integrity & Architecture Check",
        "",
    ]

    # Findings grouped by checker
    findings_by_checker = defaultdict(list)
    for f in report.findings:
        findings_by_checker[f.checker].append(f)

    # 1. Per-checker status lines
    for st in report.checkers:
        findings = findings_by_checker.get(st.name, [])
        errors = [f for f in findings if f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]
        infos = [f for f in findings if f.severity == "info"]

        if st.status == "ok":
            info_note = f" ({len(infos)} info)" if infos else ""
            lines.append(f"  ✅ [{st.name}] Clean{info_note} ({st.duration_ms:.1f}ms)")
        elif st.status == "warning":
            lines.append(f"  ⚠️  [{st.name}] {len(warnings)} warning(s) ({st.duration_ms:.1f}ms)")
        else:
            lines.append(f"  ❌ [{st.name}] {len(errors)} error(s) ({st.duration_ms:.1f}ms)")

    # 2. Detailed findings (if any warnings or errors or error status)
    notable_findings = [f for f in report.findings if f.severity in ("error", "warning")]
    if notable_findings:
        lines.append("")
        lines.append("Findings:")
        for f in notable_findings:
            icon = "❌" if f.severity == "error" else "⚠️ "
            loc = f" in {f.file}" if f.file else ""
            if f.line:
                loc += f":{f.line}"
            lines.append(f"  {icon} [{f.checker}] {f.message}{loc}")

    lines.append("")
    lines.append("─" * 60)
    summary = report.summary
    summary_text = (
        f"Summary: {summary.get('checkers_run', 0)} checkers run | "
        f"{summary.get('errors', 0)} error(s), "
        f"{summary.get('warnings', 0)} warning(s), "
        f"{summary.get('info', 0)} info "
        f"({report.duration_ms:.1f}ms)"
    )
    lines.append(summary_text)

    if report.success:
        lines.append("Result:  ✅ PASSED")
    else:
        lines.append("Result:  ❌ FAILED")

    return "\n".join(lines)
