from typing import Optional
from pydantic import BaseModel
from core.base_plugin import BasePlugin


class EventEntry(BaseModel):
    event: str
    subscribers: list[str]
    last_emitters: list[str]
    times_fired: int


class TraceEntry(BaseModel):
    id: str
    event: str
    emitter: str
    subscribers: list[str]
    payload_keys: list[str]
    timestamp: float


class SystemEventsData(BaseModel):
    events: list[EventEntry]
    recent_trace: list[TraceEntry]


class SystemEventsResponse(BaseModel):
    success: bool
    data: Optional[SystemEventsData] = None
    error: Optional[str] = None


class SystemEventsPlugin(BasePlugin):
    def __init__(self, http, event_bus):
        self.http = http
        self.event_bus = event_bus

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/events", "GET", self.execute,
            tags=["System"],
            response_model=SystemEventsResponse
        )

    async def execute(self, data: dict, context=None):
        try:
            subscribers = self.event_bus.get_subscribers()
            trace = self.event_bus.get_trace_history()

            # Build per-event stats from trace history
            stats: dict[str, dict] = {}
            for record in trace:
                name = record["event"]
                if name.startswith("_reply."):
                    continue
                if name not in stats:
                    stats[name] = {"emitters": set(), "count": 0}
                stats[name]["emitters"].add(record["emitter"])
                stats[name]["count"] += 1

            # Merge subscribers map with trace stats
            all_events = set(subscribers.keys()) | set(stats.keys())
            events = [
                EventEntry(
                    event=event,
                    subscribers=subscribers.get(event, []),
                    last_emitters=list(stats.get(event, {}).get("emitters", set())),
                    times_fired=stats.get(event, {}).get("count", 0),
                )
                for event in sorted(all_events)
                if not event.startswith("_reply.")
            ]

            recent_trace = [
                TraceEntry(**r)
                for r in reversed(trace)
                if not r["event"].startswith("_reply.")
            ][:50]

            return {"success": True, "data": {"events": events, "recent_trace": recent_trace}}
        except Exception as e:
            return {"success": False, "error": str(e)}
