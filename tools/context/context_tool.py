import os
import re
from core.base_tool import BaseTool


class ContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "context_manager"

    def setup(self):
        pass

    def get_interface_description(self) -> str:
        return """
        Context Manager Tool (context_manager):
        - PURPOSE: Automatically manages and generates live AI contextual documentation.
        - CAPABILITIES:
            - Reads the system registry.
            - Exports active tools, health status, and domain models to AI_CONTEXT.md.
            - Generates per-domain AI_CONTEXT.md files inside each domain folder.
        """

    def _scan_domain_models(self, registry):
        """
        Scans domains/*/models/*.py and registers them to the registry.
        Moved here from the Kernel to preserve the blind-kernel principle.
        """
        domains_dir = os.path.abspath("domains")
        if not os.path.exists(domains_dir):
            return
        for domain_name in sorted(os.listdir(domains_dir)):
            models_dir = os.path.join(domains_dir, domain_name, "models")
            if not os.path.isdir(models_dir):
                continue
            for filename in sorted(os.listdir(models_dir)):
                if not filename.endswith(".py") or filename == "__init__.py":
                    continue
                filepath = os.path.join(models_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        registry.register_domain_metadata(domain_name, f"model_{filename}", f.read())
                except Exception as e:
                    print(f"[ContextTool] Error reading model {filepath}: {e}")

    def on_boot_complete(self, container):
        registry = container.registry
        self._scan_domain_models(registry)
        self._generate_global_manifest(container)

    # ── Global manifest ───────────────────────────────────────────────────────

    def _generate_global_manifest(self, container):
        manifest = "# 📜 SYSTEM MANIFEST\n\n"
        manifest += "> **NOTICE:** This is a LIVE inventory. For implementation guides, read [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).\n\n"

        manifest += "## 🏗️ Quick Architecture Ref\n"
        manifest += "- **Pattern**: `__init__` (DI) -> `on_boot` (Register) -> handler methods (Action).\n"
        manifest += "- **Injection**: Tools are injected by name in the constructor.\n\n"

        manifest += "## 🛠️ Available Tools\n"
        manifest += "Check method signatures before implementation.\n\n"

        for name in container.list_tools():
            try:
                tool = container.get(name)
                status_emoji = "✅" if tool else "❌"
                manifest += f"### 🔧 Tool: `{name}` (Status: {status_emoji})\n"
                manifest += "```text\n"
                manifest += str(tool.get_interface_description()).strip()
                manifest += "\n```\n\n"
            except Exception as e:
                manifest += f"### 🔧 Tool: `{name}` (Status: ❌)\n"
                manifest += f"Error extracting info: {e}\n\n"

        manifest += "## 📦 Domains\n\n"

        dump = container.registry.get_system_dump()
        plugins_by_domain: dict[str, list[tuple[str, dict]]] = {}
        for plugin_name, info in dump.get("plugins", {}).items():
            domain = info.get("domain")
            if domain:
                plugins_by_domain.setdefault(domain, []).append((plugin_name, info))

        for domain in sorted(plugins_by_domain.keys()):
            plugins = plugins_by_domain[domain]
            plugin_names = [p[0] for p in plugins]

            all_deps: set[str] = set()
            for _, info in plugins:
                all_deps.update(info.get("dependencies", []))

            endpoints = self._get_domain_endpoints(domain, container)
            emitted = self._scan_published_events(domain)
            consumed = self._get_consumed_events(plugin_names, container)
            tables = self._get_domain_tables(domain)

            manifest += f"### `{domain}`\n"
            manifest += f"- **Tables**: {', '.join(tables) if tables else 'none'}\n"
            if endpoints:
                manifest += f"- **Endpoints**: {', '.join(endpoints)}\n"
            else:
                manifest += "- **Endpoints**: none\n"
            manifest += f"- **Events emitted**: {', '.join(sorted(emitted)) if emitted else 'none'}\n"
            manifest += f"- **Events consumed**: {', '.join(sorted(consumed)) if consumed else 'none'}\n"
            manifest += f"- **Dependencies**: {', '.join(sorted(all_deps)) if all_deps else 'none'}\n"
            manifest += f"- **Plugins**: {', '.join(sorted(plugin_names))}\n\n"

        try:
            with open("AI_CONTEXT.md", "w", encoding="utf-8") as f:
                f.write(manifest)
        except Exception as e:
            print(f"[ContextTool] Error writing AI_CONTEXT.md: {e}")

    def _get_domain_endpoints(self, domain: str, container) -> list[str]:
        try:
            http = container.get("http")
            tag = domain.capitalize()
            routes = []
            for route in http.app.routes:
                if hasattr(route, "tags") and tag in (route.tags or []):
                    methods = "/".join(sorted(route.methods - {"HEAD"} if route.methods else set()))
                    routes.append(f"{methods} {route.path}")
            return sorted(routes)
        except Exception:
            return []

    def _get_consumed_events(self, plugin_names: list[str], container) -> set[str]:
        try:
            event_bus = container.get("event_bus")
            consumed = set()
            for event, subs in event_bus.get_subscribers().items():
                if event.startswith("_reply."):
                    continue
                for sub in subs:
                    if sub.split(".")[0] in plugin_names:
                        consumed.add(event)
                        break
            return consumed
        except Exception:
            return set()

    def _scan_published_events(self, domain: str) -> set[str]:
        events: set[str] = set()
        plugins_dir = os.path.join("domains", domain, "plugins")
        if not os.path.isdir(plugins_dir):
            return events
        for filename in os.listdir(plugins_dir):
            if not filename.endswith(".py"):
                continue
            try:
                with open(os.path.join(plugins_dir, filename), "r", encoding="utf-8") as f:
                    content = f.read()
                events.update(re.findall(r'\.publish\(\s*["\']([^"\']+)["\']', content))
            except Exception:
                pass
        return events

    def _get_domain_tables(self, domain: str) -> list[str]:
        models_dir = os.path.join("domains", domain, "models")
        if not os.path.isdir(models_dir):
            return []
        return sorted([
            f.replace(".py", "")
            for f in os.listdir(models_dir)
            if f.endswith(".py") and f != "__init__.py"
        ])
