import ast
import os
import re
from core.base_tool import BaseTool

# Table ownership is read from the migration PATH, so only the NAME is parsed here.
# finditer (not search): one .sql file may declare several tables.
_CREATE_TABLE_RE = re.compile(
    r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`\[]?([A-Za-z_][A-Za-z0-9_]*)""",
    re.IGNORECASE,
)


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
            - Embeds the plugin authoring guide (tools/context/authoring_guide.md):
              executor rules plus one complete template per deliverable type, so the
              manifest alone is enough to write a plugin or its tests.
            - Regenerates AI_CONTEXT.md on every boot — always up to date with the live system.
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

    async def on_boot_complete(self, container):
        registry = container.registry
        self._scan_domain_models(registry)
        self._generate_global_manifest(container, await self._fetch_live_schema(container))

    async def _fetch_live_schema(self, container) -> dict:
        """
        The real schema, read from the database itself.

        The manifest describes TABLES from here and never from the entity models:
        a model is a hand-written mirror and can drift (it did — the manifest used
        to name the table after the model FILE, so `scheduler_one_shots` was
        published as `scheduler_one_shot`). Introspection cannot drift: it reports
        what exists.

        Safe by the time this runs: migrations are applied in the db tool's
        setup(), and the Kernel awaits every setup() together before any
        on_boot_complete. A system with no db tool still gets its manifest.
        """
        try:
            return await container.get("db").describe_schema()
        except Exception as e:
            print(f"[ContextTool] Live schema unavailable, tables omitted from manifest: {e}")
            return {}

    # ── Global manifest ───────────────────────────────────────────────────────

    def _generate_global_manifest(self, container, schema: dict):
        manifest = "# 📜 SYSTEM MANIFEST\n\n"
        manifest += "> This file is ALL you need to build a plugin. For advanced topics (testing, observability, creating tools), see [INSTRUCTIONS_FOR_AI.md](INSTRUCTIONS_FOR_AI.md).\n\n"

        manifest += self._generate_plugin_quick_start()

        manifest += "## 🛠️ Quick Architecture Ref\n"
        manifest += "- **Pattern**: `__init__` (DI) -> `on_boot` (Register) -> handler methods (Action).\n"
        manifest += "- **Injection**: Tools are injected by name in the constructor.\n\n"

        manifest += "## 🛠️ Available Tools\n"
        manifest += "Check method signatures before implementation.\n\n"

        for name in container.list_tools():
            try:
                tool = container.get(name)
                description = str(tool.get_interface_description()).strip()
                if not description:
                    print(f"[ContextTool] WARNING: Tool '{name}' has no interface description. "
                          f"Update get_interface_description() in its class.")
                status_emoji = "✅" if tool else "❌"
                manifest += f"### 🔧 Tool: `{name}` (Status: {status_emoji})\n"
                manifest += "```text\n"
                manifest += description
                manifest += "\n```\n\n"
            except Exception as e:
                manifest += f"### 🔧 Tool: `{name}` (Status: ❌)\n"
                manifest += f"Error extracting info: {e}\n\n"

        manifest += "## 📦 Domains\n\n"

        # Two sources, each asked only what it alone can know: the migration path
        # says WHICH DOMAIN owns a table (the database has no notion of domains),
        # the live schema says WHAT THE TABLE IS.
        owned_tables = self._scan_migration_tables()

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

            endpoints = self._get_domain_endpoints(domain)
            emitted_map = self._scan_published_events(domain)
            consumed = self._get_consumed_events(plugin_names, container)
            tables = owned_tables.get(domain, [])

            manifest += f"### `{domain}`\n"
            # Two lines, two questions. Table = storage, for writing SQL.
            # Model = the domain's vocabulary, for naming and shaping what the
            # API speaks. They differ on purpose (see _describe_models).
            if tables:
                for table in tables:
                    manifest += f"- **Table `{table}`** (storage): {self._describe_table(schema, table)}\n"
            else:
                manifest += "- **Tables**: none\n"

            for model in self._describe_models(domain):
                manifest += f"- {model}\n"

            if endpoints:
                manifest += "- **Endpoints**:\n"
                for ep in endpoints:
                    if " (" in ep:
                        path_part, schema_part = ep.split(" (", 1)
                        manifest += f"  - `{path_part}`\n"
                        schema_part = schema_part.rstrip(")")
                        if "; res: " in schema_part:
                            req_info, res_info = schema_part.split("; res: ", 1)
                            req_info = req_info.replace("req: ", "", 1)
                            manifest += f"    - **req**: {req_info}\n"
                            manifest += f"    - **res**: {self._clean_res_info(res_info)}\n"
                        elif schema_part.startswith("req: "):
                            req_info = schema_part.replace("req: ", "", 1)
                            manifest += f"    - **req**: {req_info}\n"
                        elif schema_part.startswith("res: "):
                            res_info = schema_part.replace("res: ", "", 1)
                            manifest += f"    - **res**: {self._clean_res_info(res_info)}\n"
                    else:
                        manifest += f"  - `{ep}`\n"
            else:
                manifest += "- **Endpoints**: none\n"
            
            if emitted_map:
                emitted_strs = [f"`{name}` ({', '.join(sorted(keys))})" for name, keys in sorted(emitted_map.items())]
                manifest += f"- **Events emitted**: {', '.join(emitted_strs)}\n"
            else:
                manifest += "- **Events emitted**: none\n"

            manifest += f"- **Events consumed**: {', '.join(sorted(consumed)) if consumed else 'none'}\n"
            manifest += f"- **Dependencies**: {', '.join(sorted(all_deps)) if all_deps else 'none'}\n"
            manifest += f"- **Plugins**: {', '.join(sorted(plugin_names))}\n\n"

        manifest += self._load_authoring_guide()

        try:
            with open("AI_CONTEXT.md", "w", encoding="utf-8") as f:
                f.write(manifest)
        except Exception as e:
            print(f"[ContextTool] Error writing AI_CONTEXT.md: {e}")

    def _clean_res_info(self, res_info: str) -> str:
        """Strips standard envelope wrapper boilerplate (success: bool, Optional, error: Optional[str])
        to present a clean, ultra-compact response payload model."""
        if "data: " in res_info:
            data_part = res_info.split("data: ", 1)[1]
            if ", error: " in data_part:
                data_part = data_part.rsplit(", error: ", 1)[0]
            data_part = data_part.strip()
            if data_part.startswith("Optional[") and data_part.endswith("]"):
                data_part = data_part[9:-1].strip()
            return data_part
        return res_info

    def _load_authoring_guide(self) -> str:
        """The plugin authoring guide (executor rules + one template per
        deliverable type) is maintained next to this tool and embedded
        verbatim, so the manifest stays the single self-sufficient artifact
        for writing a plugin or its tests."""
        path = os.path.join(os.path.dirname(__file__), "authoring_guide.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip() + "\n"
        except Exception as e:
            print(f"[ContextTool] Error reading authoring guide: {e}")
            return ""

    def _generate_plugin_quick_start(self) -> str:
        return """## ⚡ Operating Context
This file contains the technical signature of active tools and domains in the system.
For plugin development guides, critical rules, and syntax examples, see [AGENTS.md](AGENTS.md).

---

"""

    def _extract_ast_models(self, tree: ast.AST) -> dict[str, str]:
        models: dict[str, dict[str, str]] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                fields = {}
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        try:
                            type_str = ast.unparse(item.annotation)
                        except Exception:
                            type_str = "any"
                        fields[item.target.id] = type_str
                if fields:
                    models[node.name] = fields

        formatted: dict[str, str] = {}
        sorted_model_names = sorted(models.keys(), key=len, reverse=True)
        for name, fields in models.items():
            field_strs = []
            for f_name, f_type in fields.items():
                for sub_name in sorted_model_names:
                    if sub_name != name and re.search(r'\b' + re.escape(sub_name) + r'\b', f_type):
                        sub_f_str = ", ".join(f"{k}: {v}" for k, v in models[sub_name].items())
                        f_type = re.sub(r'\b' + re.escape(sub_name) + r'\b', f"{sub_name}({sub_f_str})", f_type)
                field_strs.append(f"{f_name}: {f_type}")
            formatted[name] = ", ".join(field_strs)
        return formatted

    def _get_domain_endpoints(self, domain: str) -> list[str]:
        """
        AST analysis of plugin source files to extract endpoints and their request/response schemas.
        More robust than regex.
        """
        endpoints: set[str] = set()
        plugins_dir = os.path.join("domains", domain, "plugins")
        if not os.path.isdir(plugins_dir):
            return []

        for filename in os.listdir(plugins_dir):
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(plugins_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                
                ast_models = self._extract_ast_models(tree)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        method_name = node.func.attr
                        
                        # 1. add_endpoint
                        if method_name == "add_endpoint":
                            path, method = None, None
                            req_model_name, res_model_name = None, None

                            # Positional args
                            if len(node.args) >= 1 and isinstance(node.args[0], ast.Constant):
                                path = node.args[0].value
                            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                                method = node.args[1].value

                            # Keyword args
                            for kw in node.keywords:
                                if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                                    path = kw.value.value
                                if kw.arg == "method" and isinstance(kw.value, ast.Constant):
                                    method = kw.value.value
                                if kw.arg == "request_model" and isinstance(kw.value, ast.Name):
                                    req_model_name = kw.value.id
                                if kw.arg == "response_model" and isinstance(kw.value, ast.Name):
                                    res_model_name = kw.value.id
                            
                            if path and method:
                                schema_parts = []
                                if req_model_name and req_model_name in ast_models:
                                    schema_parts.append(f"req: {ast_models[req_model_name]}")
                                if res_model_name and res_model_name in ast_models:
                                    schema_parts.append(f"res: {ast_models[res_model_name]}")

                                if schema_parts:
                                    endpoints.add(f"{method.upper()} {path} ({'; '.join(schema_parts)})")
                                else:
                                    endpoints.add(f"{method.upper()} {path}")

                        # 2. SSE
                        elif method_name == "add_sse_endpoint":
                            path = None
                            if node.args and isinstance(node.args[0], ast.Constant): path = node.args[0].value
                            for kw in node.keywords:
                                if kw.arg == "path" and isinstance(kw.value, ast.Constant): path = kw.value.value
                            if path: endpoints.add(f"SSE {path}")

                        # 3. WS
                        elif method_name == "add_ws_endpoint":
                            path = None
                            if node.args and isinstance(node.args[0], ast.Constant): path = node.args[0].value
                            for kw in node.keywords:
                                if kw.arg == "path" and isinstance(kw.value, ast.Constant): path = kw.value.value
                            if path: endpoints.add(f"WS {path}")

            except Exception as e:
                print(f"[ContextTool] Error parsing AST for {filepath}: {e}")
        
        return sorted(endpoints)


    def _get_consumed_events(self, plugin_names: list[str], container) -> set[str]:
        try:
            event_bus = container.get("event_bus")
            consumed = set()
            for event, subs in event_bus.get_subscribers().items():
                if event.startswith("_reply."):
                    continue
                for sub in subs:
                    # sub is "module.ClassName.method_name" (module-qualified
                    # so derived consumer groups never collide across domains)
                    parts = sub.split(".")
                    if len(parts) < 3:
                        continue  # plain-function subscriber, not a plugin method
                    sub_class = parts[-2]
                    # plugin_names contains "domain.ClassName"
                    if any(p.endswith(f".{sub_class}") or p == sub_class for p in plugin_names):
                        consumed.add(event)
                        break
            return consumed
        except Exception:
            return set()

    def _scan_published_events(self, domain: str) -> dict[str, set[str]]:
        """
        AST analysis to find .publish() calls.
        Returns a dict: { "event.name": {"key1", "key2", ...} }
        """
        event_map: dict[str, set[str]] = {}
        plugins_dir = os.path.join("domains", domain, "plugins")
        if not os.path.isdir(plugins_dir):
            return event_map

        for filename in os.listdir(plugins_dir):
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(plugins_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())

                # Module-level class fields, so Payload(...).model_dump() publishes
                # resolve to the payload model's field names.
                class_fields: dict[str, set[str]] = {}
                for n in tree.body:
                    if isinstance(n, ast.ClassDef):
                        fields = {
                            s.target.id for s in n.body
                            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
                        }
                        if fields:
                            class_fields[n.name] = fields

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        if node.func.attr == "publish":
                            event_name, keys = None, set()

                            # First arg is event name
                            if node.args and isinstance(node.args[0], ast.Constant):
                                event_name = node.args[0].value

                            # Second arg is payload: dict literal or Payload(...).model_dump()
                            if len(node.args) >= 2:
                                payload = node.args[1]
                                if isinstance(payload, ast.Dict):
                                    for k in payload.keys:
                                        if isinstance(k, ast.Constant):
                                            keys.add(str(k.value))
                                elif (isinstance(payload, ast.Call)
                                      and isinstance(payload.func, ast.Attribute)
                                      and payload.func.attr == "model_dump"
                                      and isinstance(payload.func.value, ast.Call)
                                      and isinstance(payload.func.value.func, ast.Name)):
                                    keys.update(class_fields.get(payload.func.value.func.id, set()))

                            if event_name:
                                if event_name not in event_map:
                                    event_map[event_name] = keys
                                else:
                                    event_map[event_name].update(keys)
            except Exception:
                pass
        return event_map

    def _scan_migration_tables(self) -> dict[str, list[str]]:
        """
        domain -> tables it declares, read from domains/{domain}/migrations/*.sql.

        Ownership is an architectural decision, so its source is the file PATH —
        the only place that records it. Only table NAMES are parsed, never
        columns: a later `ALTER TABLE ADD COLUMN` would make a parsed structure
        lie, while a name never moves. Structure comes from the live schema.
        """
        owned: dict[str, list[str]] = {}
        domains_dir = "domains"
        if not os.path.isdir(domains_dir):
            return owned

        for domain in sorted(os.listdir(domains_dir)):
            migrations_dir = os.path.join(domains_dir, domain, "migrations")
            if not os.path.isdir(migrations_dir):
                continue
            tables: list[str] = []
            for filename in sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql")):
                try:
                    with open(os.path.join(migrations_dir, filename), "r", encoding="utf-8") as f:
                        sql = f.read()
                except Exception as e:
                    print(f"[ContextTool] Error reading migration {filename}: {e}")
                    continue
                for match in _CREATE_TABLE_RE.finditer(sql):
                    name = match.group(1)
                    if name not in tables:
                        tables.append(name)
            if tables:
                owned[domain] = sorted(tables)
        return owned

    def _describe_models(self, domain: str) -> list[str]:
        """
        The domain's entity models — its UBIQUITOUS LANGUAGE.

        Deliberately NOT the table: the model is a design decision the plan
        makes, and it is supposed to differ from storage. `password_hash` is a
        column and must never be a model field; `roles` is `text` on disk and
        `list[str]` in the domain. That difference is exactly what tells a
        feature author what the API speaks and what it must never expose.

        Read from domains/{domain}/models/*.py. Not derivable from anything —
        which is why it is hand-written and why a plan declares it.
        """
        models_dir = os.path.join("domains", domain, "models")
        if not os.path.isdir(models_dir):
            return []

        described = []
        for filename in sorted(f for f in os.listdir(models_dir)
                               if f.endswith(".py") and f != "__init__.py"):
            path = os.path.join(models_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception as e:
                print(f"[ContextTool] Error parsing model {path}: {e}")
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        try:
                            type_str = ast.unparse(item.annotation)
                        except Exception:
                            type_str = "any"
                        fields.append(f"{item.target.id}: {type_str}")
                if fields:
                    described.append(
                        f"**Model `{node.name}`** (domain vocabulary): {', '.join(fields)}"
                    )
        return described

    def _describe_table(self, schema: dict, table: str) -> str:
        """Renders one table's real columns. Never guesses: if the migration
        declares a table the database does not have, that is reported as-is —
        it means the migration did not run."""
        info = schema.get(table)
        if info is None:
            return "⚠️ declared in a migration but ABSENT from the live database"

        rendered = []
        for col in info.get("columns", []):
            flags = []
            if col.get("primary_key"):
                flags.append("PK")
            elif not col.get("nullable", True):
                flags.append("NOT NULL")
            if col.get("default") is not None:
                flags.append(f"default {col['default']}")
            suffix = ", " + ", ".join(flags) if flags else ""
            rendered.append(f"{col['name']} ({col['type']}{suffix})")

        line = ", ".join(rendered)
        for cols in info.get("unique", []):
            line += f" — UNIQUE({', '.join(cols)})"
        for fk in info.get("foreign_keys", []):
            line += (f" — FK {fk['column']} → "
                     f"{fk['references_table']}.{fk['references_column']}")
        return line

