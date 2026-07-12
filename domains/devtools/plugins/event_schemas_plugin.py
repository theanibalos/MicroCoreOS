import importlib.util
import os
from typing import Optional
from pydantic import BaseModel
from core.base_plugin import BasePlugin


class EventSchemasData(BaseModel):
    schemas: dict = {}


class EventSchemasResponse(BaseModel):
    success: bool
    data: Optional[EventSchemasData] = None
    error: Optional[str] = None


class EventSchemasPlugin(BasePlugin):
    """
    GET /system/events/schemas — the event contract catalog: one JSON Schema
    per published event, generated from the Payload(BaseModel) each publisher
    plugin owns.

    This is the seed of a schema registry: when the event bus is swapped to a
    distributed broker (Kafka — Roadmap Issue 18), these are exactly the
    schemas the registry ingests, with zero plugin changes.

    Sources the (event -> model, file) map that EventContractLinterPlugin
    registers in the registry metadata at boot, imports each publisher plugin
    file, and calls model_json_schema() on the real Pydantic class. Loading a
    plugin module only defines classes (plugins act via instances the Kernel
    creates), so re-importing here is side-effect free by convention. Results
    are cached after the first request.
    """

    def __init__(self, container, http, logger):
        self.registry = container.registry
        self.http = http
        self.logger = logger
        self._cache = None

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/events/schemas", "GET", self.get_schemas,
            tags=["System"],
            response_model=EventSchemasResponse,
        )

    async def get_schemas(self, data: dict, context=None):
        try:
            if self._cache is None:
                self._cache = self._build_catalog()
            return {"success": True, "data": {"schemas": self._cache}}
        except Exception as e:
            self.logger.error(f"[EventSchemas] Failed to build catalog: {e}")
            return {"success": False, "error": "Could not build event schema catalog"}

    def _build_catalog(self) -> dict:
        meta = self.registry.get_domain_metadata().get("devtools", {})
        entries = meta.get("event_payload_models", [])
        catalog: dict[str, list] = {}
        for entry in entries:
            model = self._load_model(entry["domain"], entry["file"], entry["model"])
            if model is None:
                continue
            record = {
                "model": entry["model"],
                "domain": entry["domain"],
                "file": entry["file"],
                "json_schema": model.model_json_schema(),
            }
            bucket = catalog.setdefault(entry["event"], [])
            if not any(r["model"] == record["model"] and r["file"] == record["file"]
                       for r in bucket):
                bucket.append(record)
        return catalog

    def _load_model(self, domain: str, filename: str, class_name: str):
        path = os.path.join("domains", domain, "plugins", filename)
        try:
            spec = importlib.util.spec_from_file_location(
                f"event_schemas_{domain}_{filename[:-3]}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls = getattr(module, class_name, None)
            if isinstance(cls, type) and issubclass(cls, BaseModel):
                return cls
            self.logger.warning(
                f"[EventSchemas] '{class_name}' in {path} is not a BaseModel — skipped"
            )
        except Exception as e:
            self.logger.warning(f"[EventSchemas] Could not load {class_name} from {path}: {e}")
        return None
