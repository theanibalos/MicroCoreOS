from typing import Optional
from pydantic import BaseModel
from microcoreos import BasePlugin


class TraceToolCall(BaseModel):
    caller: str = "system"
    tool: str
    method: str
    duration_ms: float
    success: bool
    error: Optional[str] = None
    timestamp: float


class TraceNode(BaseModel):
    id: str
    parent_id: Optional[str] = None
    event: str
    emitter: str
    subscribers: list[str]
    payload_keys: list[str]
    timestamp: float
    key: Optional[str] = None
    priority: Optional[int] = None
    delay: Optional[int] = None
    tool_calls: list[TraceToolCall] = []
    children: list["TraceNode"] = []

TraceNode.model_rebuild()

class SystemTracesTreeResponse(BaseModel):
    success: bool
    data: Optional[list[TraceNode]] = None
    error: Optional[str] = None

class TraceFlatNode(BaseModel):
    id: str
    parent_id: Optional[str] = None
    event: str
    emitter: str
    subscribers: list[str]
    payload_keys: list[str]
    timestamp: float
    key: Optional[str] = None
    priority: Optional[int] = None
    delay: Optional[int] = None
    tool_calls: list[TraceToolCall] = []

class SystemTracesFlatResponse(BaseModel):
    success: bool
    data: Optional[list[TraceFlatNode]] = None
    error: Optional[str] = None


class SystemTracesPlugin(BasePlugin):
    """
    Exposes the event bus trace log in hierarchical and flat formats.
    """

    def __init__(self, http, event_bus, registry=None):
        self.http = http
        self.event_bus = event_bus
        self.registry = registry

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/traces/tree", "GET", self.get_tree,
            tags=["System"],
            response_model=SystemTracesTreeResponse
        )
        self.http.add_endpoint(
            "/system/traces/flat", "GET", self.get_flat,
            tags=["System"],
            response_model=SystemTracesFlatResponse
        )

    def _get_merged_records(self) -> list[dict]:
        history = self.event_bus.get_trace_history()
        records = [r for r in history if not r.envelope.event.startswith("_reply.")]
        
        merged: dict[str, dict] = {}
        for r in records:
            eid = r.envelope.id
            if eid not in merged:
                env = r.envelope
                merged[eid] = {
                    "id": env.id,
                    "parent_id": env.parent_id,
                    "event": env.event,
                    "emitter": env.emitter,
                    "subscribers": list(r.subscribers) if r.subscribers else [],
                    "payload_keys": list(env.payload.keys()),
                    "timestamp": float(env.timestamp.timestamp()),
                    "key": env.key,
                    "priority": env.priority,
                    "delay": env.delay,
                    "tool_calls": [],
                }
            else:
                if r.subscribers:
                    for sub in r.subscribers:
                        if sub not in merged[eid]["subscribers"]:
                            merged[eid]["subscribers"].append(sub)

        if self.registry is not None:
            by_event: dict[str, list[dict]] = {}
            for m in self.registry.get_metrics():
                ev_id = m.get("event_id")
                if not ev_id:
                    continue
                by_event.setdefault(ev_id, []).append({
                    "caller": m.get("caller", "system"),
                    "tool": m["tool"],
                    "method": m["method"],
                    "duration_ms": m["duration_ms"],
                    "success": m["success"],
                    "error": m.get("error"),
                    "timestamp": m["timestamp"],
                })
            for eid, node in merged.items():
                calls = []
                parent_id = node.get("parent_id")
                if parent_id and parent_id not in merged and parent_id in by_event:
                    calls.extend(by_event[parent_id])
                if eid in by_event:
                    calls.extend(by_event[eid])
                node["tool_calls"] = calls

        return list(merged.values())

    async def get_flat(self, data: dict, context=None):
        try:
            flat_list = self._get_merged_records()
            flat_list.sort(key=lambda x: x["timestamp"], reverse=True)
            return {"success": True, "data": flat_list}
        except Exception as e:
            print(f"[SystemTraces] Error: {e}")
            return {"success": False, "error": "Could not retrieve traces"}

    async def get_tree(self, data: dict, context=None):
        try:
            records = self._get_merged_records()
            nodes = {
                r["id"]: {
                    **r,
                    "children": []
                }
                for r in records
            }

            roots = []
            for r in records:
                node_dict = nodes[r["id"]]
                parent_id = r["parent_id"]

                if parent_id and parent_id in nodes:
                    nodes[parent_id]["children"].append(node_dict)
                else:
                    roots.append(node_dict)

            roots.sort(key=lambda x: x["timestamp"], reverse=True)
            return {"success": True, "data": roots}
        except Exception as e:
            print(f"[SystemTraces] Error: {e}")
            return {"success": False, "error": "Could not retrieve traces"}

