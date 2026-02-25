import os
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

        # Scan domain models (Kernel is now blind to domain internals)
        self._scan_domain_models(registry)

        # 1. Header
        manifest = "# 📜 SYSTEM MANIFEST\n\n"
        manifest += "> **NOTICE:** This is a LIVE inventory. For implementation guides, read [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).\n\n"

        manifest += "## 🏗️ Quick Architecture Ref\n"
        manifest += "- **Pattern**: `__init__` (DI) -> `on_boot` (Register) -> handler methods (Action).\n"
        manifest += "- **Injection**: Tools are injected by name in the constructor.\n\n"

        # 2. Dynamic Tool Listing
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

        # 3. Domain Models
        manifest += "## 📦 Domain Models\n"
        manifest += "Read the models folder for the domain you are working on before implementing a plugin.\n\n"

        domain_metadata = registry.get_domain_metadata()
        for domain_name in sorted(domain_metadata.keys()):
            manifest += f"- `{domain_name}` → `domains/{domain_name}/models/`\n"

        # 4. Write the file
        try:
            with open("AI_CONTEXT.md", "w", encoding="utf-8") as f:
                f.write(manifest)
        except Exception as e:
            print(f"[ContextTool] Error writing manifest: {e}")
