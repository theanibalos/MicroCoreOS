from typing import Optional
from pydantic import BaseModel
from microcoreos import BasePlugin
from microcoreos_dev.lint import run_checks
from microcoreos_dev.lint.checkers.events import check_event_contracts


class LintFinding(BaseModel):
    code: str
    severity: str
    event: Optional[str] = None
    publisher: Optional[str] = None
    consumer: Optional[str] = None
    detail: str


class SystemLintData(BaseModel):
    discovery_naming_violations: list[str] = []
    arch_violations: list[str] = []
    drift_warnings: list[str] = []
    event_contract_violations: list[LintFinding] = []
    route_collisions: list[str] = []
    table_ownership_warnings: list[str] = []
    field_divergence_warnings: list[str] = []
    dead_path_warnings: list[str] = []


class SystemLintResponse(BaseModel):
    success: bool
    data: Optional[SystemLintData] = None
    error: Optional[str] = None


class SystemLintPlugin(BasePlugin):
    """Unified system linter plugin.

    Runs microcoreos architecture checkers at boot, logs diagnostics to console,
    and exposes GET /system/lint aggregating all findings.
    """

    def __init__(self, container, logger, http):
        self.container = container
        self.registry = container.registry
        self.logger = logger
        self.http = http
        self._cache: Optional[SystemLintData] = None

    async def on_boot(self):
        # 1. Run event contract static scan to extract payload schemas and contract findings
        findings, publishers_meta, raw_event_findings = check_event_contracts(root=".")
        self.registry.register_domain_metadata("devtools", "event_payload_models", publishers_meta)

        # 2. Run all unified checkers
        report = run_checks(root=".")

        discovery_naming = [f.message for f in report.findings if f.checker == "discovery_naming"]
        arch = [f.message for f in report.findings if f.checker == "domain_isolation"]
        drift = [f.message for f in report.findings if f.checker == "tool_doc_drift"]
        route = [f.message for f in report.findings if f.checker == "route_collisions"]
        tables = [f.message for f in report.findings if f.checker == "table_ownership"]
        divergence = [f.message for f in report.findings if f.checker == "field_divergence"]

        event_violations = [
            LintFinding(
                code=f["code"],
                severity=f["severity"],
                event=f.get("event"),
                publisher=f.get("publisher"),
                consumer=f.get("consumer"),
                detail=f.get("detail", ""),
            )
            for f in raw_event_findings
        ]

        self._cache = SystemLintData(
            discovery_naming_violations=discovery_naming,
            arch_violations=arch,
            drift_warnings=drift,
            event_contract_violations=event_violations,
            route_collisions=route,
            table_ownership_warnings=tables,
            field_divergence_warnings=divergence,
            dead_path_warnings=[],
        )

        # 3. Publish metadata to registry for backward compatibility and introspection
        self.registry.register_domain_metadata("devtools", "discovery_naming_violations", discovery_naming)
        self.registry.register_domain_metadata("devtools", "arch_violations", arch)
        self.registry.register_domain_metadata("devtools", "drift_warnings", drift)
        self.registry.register_domain_metadata("devtools", "route_collisions", route)
        self.registry.register_domain_metadata("devtools", "table_ownership_warnings", tables)
        self.registry.register_domain_metadata("devtools", "field_divergence_warnings", divergence)
        self.registry.register_domain_metadata(
            "devtools", "event_contract_violations", [f.model_dump() for f in event_violations]
        )
        self.registry.register_domain_metadata("devtools", "dead_path_warnings", [])

        # 4. Log warnings and errors to console at boot
        for f in report.findings:
            if f.severity == "error":
                self.logger.error(f"[SystemLint] ❌ {f.checker}: {f.message}")
            elif f.severity == "warning":
                self.logger.warning(f"[SystemLint] ⚠️  {f.checker}: {f.message}")

        if not any(f.severity in ("error", "warning") for f in report.findings):
            self.logger.info("[SystemLint] ✅ Architecture check passed (0 violations, 0 warnings).")

        # 5. Register runtime pre-mount hook for route collisions
        if hasattr(self.http, "register_pre_mount_hook"):
            self.http.register_pre_mount_hook(self._check_runtime_route_collisions)

        # 6. Expose GET /system/lint
        self.http.add_endpoint(
            "/system/lint",
            "GET",
            self.get_lint,
            tags=["System"],
            response_model=SystemLintResponse,
        )

    def _check_runtime_route_collisions(self, endpoints: list[dict]) -> None:
        """Advisory runtime check across mounted endpoints."""
        owners_by_route: dict[tuple[str, str], set[str]] = {}
        for ep in endpoints:
            key = (ep.get("method", "").upper(), ep.get("path", ""))
            owners_by_route.setdefault(key, set()).add(ep.get("owner", "unknown"))

        collisions = [
            f"Route collision: {method} {path} registered by {', '.join(sorted(owners))} "
            f"— only the first match is reachable."
            for (method, path), owners in owners_by_route.items()
            if len(owners) > 1
        ]
        if collisions and self._cache is not None:
            for c in collisions:
                if c not in self._cache.route_collisions:
                    self._cache.route_collisions.append(c)
                    self.logger.warning(f"[SystemLint] ⚠️  {c}")
            self.registry.register_domain_metadata("devtools", "route_collisions", self._cache.route_collisions)

    async def get_lint(self, data: dict, context=None):
        try:
            if self._cache is None:
                meta = self.registry.get_domain_metadata().get("devtools", {})
                self._cache = SystemLintData(
                    discovery_naming_violations=meta.get("discovery_naming_violations", []),
                    arch_violations=meta.get("arch_violations", []),
                    drift_warnings=meta.get("drift_warnings", []),
                    event_contract_violations=meta.get("event_contract_violations", []),
                    route_collisions=meta.get("route_collisions", []),
                    table_ownership_warnings=meta.get("table_ownership_warnings", []),
                    field_divergence_warnings=meta.get("field_divergence_warnings", []),
                    dead_path_warnings=meta.get("dead_path_warnings", []),
                )
            return {"success": True, "data": self._cache.model_dump()}
        except Exception as e:
            self.logger.error(f"[SystemLint] ❌ Failed to read lint data: {e}")
            return {"success": False, "error": "Could not retrieve lint results"}
