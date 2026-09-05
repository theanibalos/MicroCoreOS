"""Event contract static analyzer and checker.

Cross-checks payload keys emitted at each publish site vs keys each
subscriber consumes.
"""

import ast
import os
from typing import Optional
from microcoreos_dev.lint.schema import CheckFinding

EXCLUDED_PREFIXES = ("_dlq.", "_reply.")


class EventContractAnalyzer:
    """Static (AST) cross-check of event bus contracts."""

    def __init__(self):
        self.publishers: list[dict] = []
        self.consumers: list[dict] = []
        self.extraction_infos: list[dict] = []

    def add_source(self, domain: str, filename: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.extraction_infos.append({
                "code": "LINT_ERROR", "severity": "info",
                "detail": f"Could not parse {domain}/{filename}: {e}",
                "event": None, "publisher": None, "consumer": None,
            })
            return

        models = self._collect_pydantic_models(tree)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._scan_plugin_class(domain, filename, node, models)

    def _collect_pydantic_models(self, tree: ast.Module) -> dict:
        models: dict[str, dict] = {}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {
                b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", None)
                for b in node.bases
            }
            if "BaseModel" not in base_names:
                continue
            required, optional = set(), set()
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                field = stmt.target.id
                if stmt.value is None:
                    required.add(field)
                elif (isinstance(stmt.value, ast.Call)
                      and getattr(stmt.value.func, "id", getattr(stmt.value.func, "attr", None)) == "Field"):
                    has_default = bool(stmt.value.args) or any(
                        kw.arg in ("default", "default_factory") for kw in stmt.value.keywords
                    )
                    (optional if has_default else required).add(field)
                else:
                    optional.add(field)
            models[node.name] = {"required": required, "optional": optional}
        return models

    def _scan_plugin_class(self, domain, filename, classdef, models) -> None:
        methods = {
            m.name: m for m in classdef.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for method in methods.values():
            for call in ast.walk(method):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                    continue
                if call.func.attr in ("publish", "request"):
                    self._extract_publish(domain, filename, classdef.name, method, call, models)
                elif call.func.attr == "subscribe":
                    self._extract_subscribe(domain, filename, classdef.name, methods, models, call)

    def _extract_publish(self, domain, filename, cls, method, call, models) -> None:
        if not call.args:
            return
        site = f"{domain}.{cls}.{method.name} ({filename}:{call.lineno})"
        event = self._literal_str(call.args[0])
        if event is None:
            self.extraction_infos.append({
                "code": "DYNAMIC_EVENT", "severity": "info", "publisher": site,
                "detail": "publish/request with a non-literal event name — not verifiable",
                "event": None, "consumer": None,
            })
            return
        if self._excluded(event):
            return

        payload_node = call.args[1] if len(call.args) > 1 else None
        keys, is_open, model = self._resolve_payload(payload_node, method, models)
        if keys is None:
            self.extraction_infos.append({
                "code": "UNKNOWN_PAYLOAD", "severity": "info", "event": event, "publisher": site,
                "detail": "payload is not a statically analyzable dict literal",
                "consumer": None,
            })
        elif model is None:
            self.extraction_infos.append({
                "code": "UNTYPED_PAYLOAD", "severity": "info", "event": event, "publisher": site,
                "detail": "payload is a raw dict — define a Payload(BaseModel) in this plugin and publish its .model_dump()",
                "consumer": None,
            })
        self.publishers.append({
            "event": event, "site": site, "keys": keys, "open": is_open,
            "model": model, "domain": domain, "file": filename, "lineno": call.lineno,
        })

    def _resolve_payload(self, node, method, models):
        if isinstance(node, ast.Dict):
            keys, is_open = set(), False
            for k in node.keys:
                if k is None:
                    is_open = True
                elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
                else:
                    is_open = True
            return keys, is_open, None
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "model_dump"
                    and not node.args and not node.keywords):
                model = self._resolve_model_name(node.func.value, method, models)
                if model is not None:
                    fields = models[model]
                    return fields["required"] | fields["optional"], False, model
        if isinstance(node, ast.Name):
            value = self._single_assignment(node, method)
            if value is not None:
                return self._resolve_payload(value, method, models)
        return None, True, None

    def _resolve_model_name(self, node, method, models):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in models:
            return node.func.id
        if isinstance(node, ast.Name):
            value = self._single_assignment(node, method)
            if value is not None:
                return self._resolve_model_name(value, method, models)
        return None

    @staticmethod
    def _single_assignment(node, method):
        assigns = [
            stmt.value for stmt in ast.walk(method)
            if isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == node.id for t in stmt.targets)
        ]
        return assigns[0] if len(assigns) == 1 else None

    def _extract_subscribe(self, domain, filename, cls, methods, models, call) -> None:
        if len(call.args) < 2:
            return
        site = f"{domain}.{cls} ({filename}:{call.lineno})"
        event = self._literal_str(call.args[0])
        if event is None:
            self.extraction_infos.append({
                "code": "DYNAMIC_EVENT", "severity": "info", "consumer": site,
                "detail": "subscribe with a non-literal event name — not verifiable",
                "event": None, "publisher": None,
            })
            return
        if self._excluded(event):
            return

        handler_node = call.args[1]
        handler = None
        if (isinstance(handler_node, ast.Attribute)
                and isinstance(handler_node.value, ast.Name)
                and handler_node.value.id == "self"):
            handler = methods.get(handler_node.attr)

        consumer_name = f"{domain}.{cls}.{getattr(handler, 'name', '?')}"
        if handler is None:
            self.consumers.append({
                "event": event, "consumer": consumer_name,
                "required": set(), "optional": set(), "opaque": True,
                "domain": domain, "file": filename, "lineno": call.lineno,
            })
            self.extraction_infos.append({
                "code": "OPAQUE_CONSUMER", "severity": "info", "event": event, "consumer": consumer_name,
                "detail": "handler could not be resolved statically",
                "publisher": None,
            })
            return

        required, optional, opaque = self._analyze_handler(handler, models)
        self.consumers.append({
            "event": event, "consumer": consumer_name,
            "required": required, "optional": optional, "opaque": opaque,
            "domain": domain, "file": filename, "lineno": call.lineno,
        })
        if opaque:
            self.extraction_infos.append({
                "code": "OPAQUE_CONSUMER", "severity": "info", "event": event, "consumer": consumer_name,
                "detail": "handler uses the payload in ways the linter cannot analyze",
                "publisher": None,
            })

    def _analyze_handler(self, handler, models):
        params = handler.args.args
        if len(params) < 2:
            return set(), set(), False
        ev = params[1].arg

        def is_payload_attr(n):
            return (isinstance(n, ast.Attribute) and n.attr == "payload"
                    and isinstance(n.value, ast.Name) and n.value.id == ev)

        aliases = {
            stmt.targets[0].id
            for stmt in ast.walk(handler)
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name) and is_payload_attr(stmt.value)
        }

        def is_payload_ref(n):
            return is_payload_attr(n) or (isinstance(n, ast.Name) and n.id in aliases)

        required, optional = set(), set()
        recognized = set()
        touched = False

        for node in ast.walk(handler):
            if isinstance(node, ast.Subscript) and is_payload_ref(node.value):
                key = self._literal_str(node.slice)
                if key is not None:
                    required.add(key)
                    recognized.add(id(node.value))
            elif isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                        and is_payload_ref(node.func.value) and node.args):
                    key = self._literal_str(node.args[0])
                    if key is not None:
                        optional.add(key)
                        recognized.add(id(node.func.value))
                elif isinstance(node.func, ast.Name) and node.func.id in models:
                    for kw in node.keywords:
                        if kw.arg is None and is_payload_ref(kw.value):
                            required |= models[node.func.id]["required"]
                            optional |= models[node.func.id]["optional"]
                            recognized.add(id(kw.value))
            if is_payload_ref(node) and id(node) not in recognized:
                touched = True

        opaque = touched and not (required or optional)
        return required, optional, opaque

    def check(self) -> list[dict]:
        findings = list(self.extraction_infos)

        events = {p["event"] for p in self.publishers} | {c["event"] for c in self.consumers}
        for event in sorted(events):
            pubs = [p for p in self.publishers if p["event"] == event]
            cons = [c for c in self.consumers if c["event"] == event]

            if pubs and not cons:
                findings.append({
                    "code": "ORPHAN_PUBLISH", "severity": "info", "event": event,
                    "publisher": ", ".join(p["site"] for p in pubs),
                    "consumer": None,
                    "detail": "event is published but has no static subscribers",
                })
            if cons and not pubs:
                findings.append({
                    "code": "ORPHAN_SUBSCRIBE", "severity": "info", "event": event,
                    "publisher": None,
                    "consumer": ", ".join(c["consumer"] for c in cons),
                    "detail": "event is subscribed to but never published statically",
                })

            for consumer in cons:
                for key in sorted(consumer["required"]):
                    for pub in pubs:
                        if pub["keys"] is None or pub["open"]:
                            continue
                        if key not in pub["keys"]:
                            findings.append({
                                "code": "MISSING_KEY", "severity": "warning", "event": event,
                                "publisher": pub["site"], "consumer": consumer["consumer"],
                                "detail": (f"consumer requires key '{key}' but this publish "
                                           f"site only sends {sorted(pub['keys'])}"),
                            })

        findings.sort(key=lambda f: (f["severity"] != "warning", f["code"], f.get("event") or ""))
        return findings

    @staticmethod
    def _literal_str(node) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    @staticmethod
    def _excluded(event: str) -> bool:
        return event.startswith(EXCLUDED_PREFIXES) or "*" in event


def check_event_contracts(
    root: str = ".",
    domains_dir: str = "domains",
) -> tuple[list[CheckFinding], list[dict]]:
    """Scan plugins for event contract compatibility."""
    analyzer = EventContractAnalyzer()
    base = os.path.join(root, domains_dir) if not os.path.isabs(domains_dir) else domains_dir
    if os.path.isdir(base):
        for domain in sorted(os.listdir(base)):
            plugins_dir = os.path.join(base, domain, "plugins")
            if not os.path.isdir(plugins_dir):
                continue
            for filename in sorted(os.listdir(plugins_dir)):
                if not filename.endswith(".py"):
                    continue
                filepath = os.path.join(plugins_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        analyzer.add_source(domain, filename, f.read())
                except Exception as e:
                    analyzer.extraction_infos.append({
                        "code": "FILE_READ_ERROR",
                        "severity": "warning",
                        "detail": f"Could not read {filename}: {e}",
                        "event": None,
                        "publisher": None,
                        "consumer": None,
                    })

    raw_findings = analyzer.check()
    findings: list[CheckFinding] = []

    for f in raw_findings:
        msg = f"{f['code']}"
        if f.get("event"):
            msg += f" {f['event']}"
        msg += f": {f['detail']}"

        findings.append(
            CheckFinding(
                checker="event_contracts",
                code=f["code"],
                severity=f["severity"],
                message=msg,
                file=None,
            )
        )

    # Publishers extracted (for EventSchemasPlugin or metadata)
    publishers_meta = [
        {"event": p["event"], "model": p["model"], "domain": p["domain"], "file": p["file"]}
        for p in analyzer.publishers if p.get("model")
    ]

    return findings, publishers_meta
