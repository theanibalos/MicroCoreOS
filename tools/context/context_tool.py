import os
from core.base_tool import BaseTool

class ContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "context_manager"

    def setup(self):
        """Does not require technical initialization of external resources."""
        pass

    def get_interface_description(self) -> str:
        return """
        Context Manager Tool (context_manager):
        - PURPOSE: Automatically manages and generates live AI contextual documentation.
        - CAPABILITIES:
            - Reads the system registry.
            - Exports active tools, health status, and domain models to AI_CONTEXT.md.
        """

    def on_boot_complete(self, container):
        """Generates the manifest using the Core's internal Registry."""
        
        # The registry is now a GUARANTEE in the container (Core)
        registry = container.registry
        
        # 1. Header (Minimalist)
        manifest = "# 📜 SYSTEM MANIFEST\n\n"
        manifest += "> **NOTICE:** This is a LIVE inventory. For implementation guides, read [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).\n\n"
        
        manifest += "## 🏗️ Quick Architecture Ref\n"
        manifest += "- **Pattern**: `__init__` (DI) -> `on_boot` (Reg) -> `execute` (Action).\n"
        manifest += "- **Injection**: Tools are injected by name in the constructor.\n\n"

        # 2. Dynamic Tool Listing (Primary focus)
        manifest += "## 🛠️ Available Tools\n"
        manifest += "Check method signatures before implementation.\n\n"
        
        for name in container.list_tools():
            try:
                tool = container.get(name)
                # Fallback purely to checking if we have the tool
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
        manifest += "Active data structures. Use these in `request_model`/`response_model`.\n\n"
        
        domain_metadata = registry.get_domain_metadata()
        for domain_name, data in sorted(domain_metadata.items()):
            manifest += f"### 🧩 Domain `{domain_name}`\n"
            found_models = False
            for key in sorted(data.keys()):
                if key.startswith("model_"):
                    model_name = key.replace("model_", "")
                    manifest += f"- Model: `{model_name}`\n"
                    found_models = True
            if not found_models:
                manifest += "- (No specialized models found)\n"
            manifest += "\n"

        # 4. Write the file
        try:
            with open("AI_CONTEXT.md", "w", encoding="utf-8") as f:
                f.write(manifest)
        except Exception as e:
            print(f"[ContextTool] Error writing manifest: {e}")