from typing import Optional
from pydantic import BaseModel
from core.base_plugin import BasePlugin


class TraceNode(BaseModel):
    id: str
    event: str
    emitter: str
    subscribers: list[str]
    payload_keys: list[str]
    timestamp: float
    children: list["TraceNode"] = []


TraceNode.model_rebuild()


class SystemTracesResponse(BaseModel):
    success: bool
    data: Optional[list[TraceNode]] = None
    error: Optional[str] = None


class SystemTracesPlugin(BasePlugin):
    """
    Exposes the causal event tree reconstructed from the event bus trace log.
    Each node knows which event caused it (parent_id), allowing full chain reconstruction.
    """

    def __init__(self, http, event_bus):
        self.http = http
        self.event_bus = event_bus

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/traces", "GET", self.execute,
            tags=["System"],
            response_model=SystemTracesResponse
        )

    async def execute(self, data: dict, context=None):
        try:
            history = self.event_bus.get_trace_history()

            # Filter internal reply channels
            records = [r for r in history if not r["event"].startswith("_reply.")]

            # Index all records by id
            nodes = {
                r["id"]: {
                    "id": r["id"],
                    "event": r["event"],
                    "emitter": r["emitter"],
                    "subscribers": r["subscribers"],
                    "payload_keys": r["payload_keys"],
                    "timestamp": r["timestamp"],
                    "children": []
                }
                for r in records
            }

            # Build tree by attaching children to their parent
            roots = []
            for r in records:
                node = nodes[r["id"]]
                parent_id = r.get("parent_id")
                if parent_id and parent_id in nodes:
                    nodes[parent_id]["children"].append(node)
                else:
                    roots.append(node)

            return {"success": True, "data": roots}
        except Exception as e:
            return {"success": False, "error": str(e)}
