"""Route collisions: two plugins registering the same (method, path) (Issue 26).

One of the linters split out of the former ArchitectureLinterPlugin. This is
the only one that needs the `http` tool — the split is what makes that visible
in the registry's per-plugin dependency list.

Registry key: devtools/route_collisions (read by GET /system/lint).
"""

from core.base_plugin import BasePlugin


class RouteCollisionLinterPlugin(BasePlugin):
    """
    Groups the http tool's buffered endpoints by (method, path). Starlette
    routes to the first match, so more than one plugin registering the same
    route means every registration after the first is silently unreachable.

    Deferred by design: add_endpoint() only BUFFERS, so this must run once
    every plugin has had a chance to register. The http tool calls it as a
    pre-mount hook — the first point where that is guaranteed.
    """

    def __init__(self, container, logger, http):
        self.registry = container.registry
        self.logger = logger
        self.http = http

    async def on_boot(self):
        self.http.register_pre_mount_hook(self._check_route_collisions)

    def _check_route_collisions(self, endpoints: list[dict]) -> None:
        """Advisory only — never blocks boot."""
        owners_by_route: dict[tuple[str, str], set[str]] = {}
        for ep in endpoints:
            key = (ep["method"].upper(), ep["path"])
            owners_by_route.setdefault(key, set()).add(ep["owner"])

        collisions = [
            f"Route collision: {method} {path} registered by {', '.join(sorted(owners))} "
            f"— only the first match is reachable."
            for (method, path), owners in owners_by_route.items()
            if len(owners) > 1
        ]

        if collisions:
            self.registry.register_domain_metadata("devtools", "route_collisions", collisions)
            for c in collisions:
                self.logger.warning(f"[RouteCollisionLinter] {c}")
        else:
            self.logger.info("[RouteCollisionLinter] No route collisions found.")
