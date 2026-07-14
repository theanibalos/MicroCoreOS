"""
ChaosControlPlugin — runtime fault injection (extras, ROADMAP Issue 34)
=========================================================================

NEVER active by default: this file lives in extras/available_domains/chaos/
until an operator opts in by copying the domain into domains/ (same
activation standard as every other extra — file placement, see
INSTRUCTIONS_FOR_AI.md "Available Extras"). It is the RUNTIME counterpart to
the existing boot-time chaos fixtures that already live in this same domain
(blocking_boot_plugin.py, failing_plugin.py, stress_plugin.py) and to
extras/available_tools/chaos (ChaosTool, which only fails at boot). This
plugin is for live experiments against a running system: "make the db 50%
flaky for the billing plugin only, watch its real retries/DLQ react".
MicroCoreBench drives it; any operator can.

SEAM (single, deliberately narrow):
────────────────────────────────────────────────────────────────────────────
Zero changes to tools/event_bus/ or tools/http_server/ — nothing outside
this file is touched. Everything here is built on the ALREADY-SANCTIONED
meta-plugin introspection precedent (see ArchitectureLinterPlugin's
container.get_raw_tools() for tool-drift scanning, ToolHealthPlugin's
container.get() for proactive health checks): this plugin takes `container`
and monkey-patches RAW tool methods (bypassing the ToolProxy at wrap time,
but every call still traverses the ToolProxy at call time — see the
DEVIATION note below), keeping the true originals for restore. The ROADMAP
explicitly names wrapping as the preferred path and a first-class ToolProxy
fault flag as only a fallback "if wrapping proves fragile" — it hasn't, so
this plugin does ONLY wrapping.

Two independent axes of fault, composed on the SAME wrapping mechanism:

1. GLOBAL tool fault — POST /system/chaos/tool {name, mode}
   mode: down (every call raises) | slow (injected asyncio.sleep, then a
   real passthrough call) | flaky (fails ~rate%) | off (clears only the
   global fault on that tool). Unconditional: affects every caller.

2. CALLER-SCOPED tool fault — POST /system/chaos/fail {plugin, tool?, rate}
   and POST /system/chaos/latency {plugin?, tool?, seconds}. The wrapped
   method only raises/delays when the CURRENT caller's identity matches
   `plugin`. Identity is read from core.context.current_identity_var — the
   SAME contextvar the logger tool's sinks already use to attribute log
   lines to a plugin (see tools/logger/logger_tool.py). It is set for the
   duration of a handler's execution by the event_bus tool (around
   `callback(envelope)` in its delivery loop) and by the http tool (around
   the request handler) — both UNCHANGED, read-only here, never written to
   by this plugin. `tool` narrows the fault to one tool; omitted = every
   currently-registered tool (a fault on a tool the target plugin never
   touches simply never fires — harmless, and the honest way to express
   "every tool this plugin touches" without static analysis of the plugin's
   source).
   Effect: the target plugin's OWN event handler (or HTTP handler) genuinely
   raises when it calls into the faulted tool — the bus's REAL
   retry/backoff/DLQ machinery (or the http tool's real 500 path) reacts
   exactly as it would to an organic failure, because from their point of
   view it IS one. This is the sad-path-per-link experiment with zero bus
   or http changes.

Both axes share ONE wrapping mechanism: the first fault (of either kind)
armed against a given tool replaces its public methods with a persistent
dispatcher that, on every call, re-reads the CURRENT list of armed
_FaultSpec entries for that tool and decides raise / sleep / passthrough.
Toggling or clearing faults afterwards never re-wraps anything — it only
mutates the spec list — so composing a global 'slow' with a plugin-scoped
'fail' on the same tool is a single, well-defined dispatcher, not a stack of
nested closures.

DEVIATION FROM THE LETTER OF THE ROADMAP (documented, not silent): the
ToolProxy (core/container.py) caches a per-method wrapper closure in
`proxy._wrapper_cache` the first time each attribute name is accessed. If a
method was already called once before this plugin wraps it, patching the raw
tool's attribute alone is not enough — the cached closure still references
the pre-patch method object, so the fault would silently never fire. To keep
the promise "calls still traverse the ToolProxy unmodified", this plugin
pops the stale entry from `proxy._wrapper_cache` at the moment it FIRST
wraps a tool (and again when it fully restores that tool), so the next call
re-resolves via `getattr(raw_tool, name)` and picks up the dispatcher (or the
restored original). Same private-attribute depth of introspection
`get_raw_tools()` already grants a meta-plugin; still zero core/ changes,
zero tools/event_bus or tools/http_server changes.

Process-death / infrastructure-down experiments are explicitly OUT of scope
here — the bench's `proc` tool covers those from outside the process; this
plugin only fakes business-logic-level tool faults from inside it.

Every action published here is a typed `system.chaos.*` event (publisher
owns the schema, per house rule), so chaos experiments appear causally in
the trace tree (GET /system/traces/tree) exactly like any other business
event.
"""

import asyncio
import inspect
import random
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.base_plugin import BasePlugin
from core.context import current_identity_var


# ── Request / Response schemas (inline, per house rule 4) ──────────────────

class ToolFaultRequest(BaseModel):
    name: str = Field(min_length=1, description="Tool injection name, e.g. 'db'.")
    mode: Literal["down", "slow", "flaky", "off"]
    seconds: float = Field(default=2.0, ge=0, description="Injected sleep, used by mode='slow'.")
    rate: float = Field(default=0.5, ge=0, le=1, description="Failure probability, used by mode='flaky'.")


class ToolFaultData(BaseModel):
    name: str
    mode: str


class ToolFaultResponse(BaseModel):
    success: bool
    data: Optional[ToolFaultData] = None
    error: Optional[str] = None


class FailRequest(BaseModel):
    plugin: str = Field(min_length=1, description="Plugin identity, '<domain>.<ClassName>'. Only calls FROM this plugin are affected.")
    tool: Optional[str] = Field(default=None, description="Narrow to one tool; omit to scope every registered tool.")
    rate: float = Field(ge=0, le=1, description="Failure probability per call (0..1).")


class FailData(BaseModel):
    plugin: str
    tool: Optional[str]
    rate: float


class FailResponse(BaseModel):
    success: bool
    data: Optional[FailData] = None
    error: Optional[str] = None


class LatencyRequest(BaseModel):
    plugin: Optional[str] = Field(default=None, description="Omit for an unconditional (every caller) delay.")
    tool: Optional[str] = Field(default=None, description="Narrow to one tool; omit to scope every registered tool.")
    seconds: float = Field(ge=0, description="Injected delay before the real call.")


class LatencyData(BaseModel):
    plugin: Optional[str]
    tool: Optional[str]
    seconds: float


class LatencyResponse(BaseModel):
    success: bool
    data: Optional[LatencyData] = None
    error: Optional[str] = None


class ResetData(BaseModel):
    cleared: int
    restored_tools: list[str]


class ResetResponse(BaseModel):
    success: bool
    data: Optional[ResetData] = None
    error: Optional[str] = None


class FaultSpecView(BaseModel):
    tool: str
    source: str    # "tool_mode" | "fail" | "latency"
    mode: str      # "down" | "slow" | "flaky"
    plugin: Optional[str] = None
    rate: Optional[float] = None
    seconds: Optional[float] = None


class ChaosStateData(BaseModel):
    faults: list[FaultSpecView]
    wrapped_tools: list[str]


class ChaosStateResponse(BaseModel):
    success: bool
    data: Optional[ChaosStateData] = None
    error: Optional[str] = None


# ── Event payload schemas (publisher owns the contract, per house rule) ────

class ChaosToolFaultArmedPayload(BaseModel):
    tool: str
    mode: str


class ChaosFailArmedPayload(BaseModel):
    plugin: str
    tool: Optional[str]
    rate: float


class ChaosLatencyArmedPayload(BaseModel):
    plugin: Optional[str]
    tool: Optional[str]
    seconds: float


class ChaosResetPayload(BaseModel):
    cleared: int


class ChaosToolFaultError(RuntimeError):
    """Raised by a chaos-wrapped tool method (mode='down', or an unlucky
    'flaky'/'fail' roll). Deliberately a PLAIN RuntimeError, not
    ToolUnavailableError: the ROADMAP intent is to exercise the plugins' real
    Safe-Error paths and the registry's EXISTING consecutive-failure DEAD
    policy (5 in a row) — the same path any ordinary business exception
    takes — not to short-circuit straight to DEAD via the infra-unavailable
    fast path."""


class _FaultSpec:
    """One armed fault. Read live (never copied) by the dispatcher on every
    call, so toggling/clearing a spec takes effect on the NEXT call with no
    re-wrapping needed."""

    __slots__ = ("tool", "source", "mode", "plugin", "rate", "seconds")

    def __init__(self, tool: str, source: str, mode: str,
                 plugin: Optional[str] = None, rate: Optional[float] = None,
                 seconds: Optional[float] = None):
        self.tool = tool
        self.source = source
        self.mode = mode
        self.plugin = plugin
        self.rate = rate
        self.seconds = seconds

    def matches_caller(self) -> bool:
        """Unscoped (plugin=None) specs always match. Scoped specs match the
        CURRENT caller's identity (see core.context.current_identity_var) by
        prefix, same convention as the bus's derived subscriber names and
        the http tool's handler identities: '<domain>.<ClassName>[.method]'.
        """
        if self.plugin is None:
            return True
        identity = current_identity_var.get()
        return identity == self.plugin or identity.startswith(self.plugin + ".")

    def to_view(self) -> "FaultSpecView":
        return FaultSpecView(
            tool=self.tool, source=self.source, mode=self.mode,
            plugin=self.plugin, rate=self.rate, seconds=self.seconds,
        )


class ChaosControlPlugin(BasePlugin):
    """
    Exposes runtime chaos experiments over HTTP. See module docstring for the
    full design and the one documented deviation from the ROADMAP's letter.
    """

    # Same exclusion set ArchitectureLinterPlugin uses for its tool-drift
    # scan — these are lifecycle/meta methods, not business capabilities,
    # and must never be faulted.
    _IGNORED_TOOL_METHODS = {
        "setup", "name", "get_interface_description", "on_boot_complete",
        "on_instrument", "shutdown", "on_boot",
    }

    def __init__(self, http, event_bus, container, logger):
        self.http = http
        self.bus = event_bus
        self.container = container
        self.logger = logger
        self._specs: list[_FaultSpec] = []
        # tool_name -> {method_name: TRUE original bound callable}. Presence
        # of a key means that tool's methods are currently wrapped by our
        # dispatcher (regardless of how many/which specs target it).
        self._tool_originals: dict[str, dict[str, callable]] = {}

    async def on_boot(self):
        self.http.add_endpoint(
            "/system/chaos/tool", "POST", self.set_tool_fault,
            tags=["Chaos"], request_model=ToolFaultRequest, response_model=ToolFaultResponse,
        )
        self.http.add_endpoint(
            "/system/chaos/fail", "POST", self.set_fail,
            tags=["Chaos"], request_model=FailRequest, response_model=FailResponse,
        )
        self.http.add_endpoint(
            "/system/chaos/latency", "POST", self.set_latency,
            tags=["Chaos"], request_model=LatencyRequest, response_model=LatencyResponse,
        )
        self.http.add_endpoint(
            "/system/chaos/reset", "POST", self.reset,
            tags=["Chaos"], response_model=ResetResponse,
        )
        self.http.add_endpoint(
            "/system/chaos", "GET", self.get_state,
            tags=["Chaos"], response_model=ChaosStateResponse,
        )
        self.logger.warning(
            "[ChaosControl] Runtime fault injection endpoints are LIVE "
            "(/system/chaos/*). This is an extras plugin — only boot it "
            "when you intend live chaos experiments."
        )

    # ── POST /system/chaos/tool ─────────────────────────────────────────────

    async def set_tool_fault(self, data: dict, context=None):
        try:
            req = ToolFaultRequest(**data)
            raw_tool = self._find_raw_tool(req.name)
            if raw_tool is None:
                return {"success": False, "error": f"Unknown tool '{req.name}'"}

            # Clear any previous GLOBAL (unscoped) mode on this tool first —
            # a second /tool call REPLACES the global mode, it doesn't stack.
            self._specs = [s for s in self._specs if not (s.tool == req.name and s.source == "tool_mode")]

            if req.mode != "off":
                self._ensure_wrapped(req.name, raw_tool)
                self._specs.append(_FaultSpec(
                    tool=req.name, source="tool_mode", mode=req.mode,
                    plugin=None, rate=req.rate, seconds=req.seconds,
                ))
            self._maybe_restore_if_unused(req.name, raw_tool)

            await self.bus.publish(
                "system.chaos.tool_fault_armed",
                ChaosToolFaultArmedPayload(tool=req.name, mode=req.mode).model_dump(),
            )
            return {"success": True, "data": ToolFaultData(name=req.name, mode=req.mode).model_dump()}
        except Exception as e:
            self.logger.error(f"[ChaosControl] set_tool_fault failed: {e}")
            return {"success": False, "error": "Could not set tool fault"}

    # ── POST /system/chaos/fail ─────────────────────────────────────────────

    async def set_fail(self, data: dict, context=None):
        try:
            req = FailRequest(**data)
            targets = self._resolve_targets(req.tool)
            if not targets:
                return {"success": False, "error": f"Unknown tool '{req.tool}'" if req.tool else "No tools registered"}

            # Replace any previous fail-spec for the SAME (plugin, tool) pair.
            self._specs = [
                s for s in self._specs
                if not (s.source == "fail" and s.plugin == req.plugin and s.tool in [t for t, _ in targets])
            ]
            for tool_name, raw_tool in targets:
                self._ensure_wrapped(tool_name, raw_tool)
                if req.rate > 0:
                    self._specs.append(_FaultSpec(
                        tool=tool_name, source="fail", mode="flaky",
                        plugin=req.plugin, rate=req.rate,
                    ))
                self._maybe_restore_if_unused(tool_name, raw_tool)

            await self.bus.publish(
                "system.chaos.fail_armed",
                ChaosFailArmedPayload(plugin=req.plugin, tool=req.tool, rate=req.rate).model_dump(),
            )
            return {
                "success": True,
                "data": FailData(plugin=req.plugin, tool=req.tool, rate=req.rate).model_dump(),
            }
        except Exception as e:
            self.logger.error(f"[ChaosControl] set_fail failed: {e}")
            return {"success": False, "error": "Could not set fail fault"}

    # ── POST /system/chaos/latency ──────────────────────────────────────────

    async def set_latency(self, data: dict, context=None):
        try:
            req = LatencyRequest(**data)
            targets = self._resolve_targets(req.tool)
            if not targets:
                return {"success": False, "error": f"Unknown tool '{req.tool}'" if req.tool else "No tools registered"}

            self._specs = [
                s for s in self._specs
                if not (s.source == "latency" and s.plugin == req.plugin and s.tool in [t for t, _ in targets])
            ]
            for tool_name, raw_tool in targets:
                self._ensure_wrapped(tool_name, raw_tool)
                if req.seconds > 0:
                    self._specs.append(_FaultSpec(
                        tool=tool_name, source="latency", mode="slow",
                        plugin=req.plugin, seconds=req.seconds,
                    ))
                self._maybe_restore_if_unused(tool_name, raw_tool)

            await self.bus.publish(
                "system.chaos.latency_armed",
                ChaosLatencyArmedPayload(plugin=req.plugin, tool=req.tool, seconds=req.seconds).model_dump(),
            )
            return {
                "success": True,
                "data": LatencyData(plugin=req.plugin, tool=req.tool, seconds=req.seconds).model_dump(),
            }
        except Exception as e:
            self.logger.error(f"[ChaosControl] set_latency failed: {e}")
            return {"success": False, "error": "Could not set latency fault"}

    # ── POST /system/chaos/reset ────────────────────────────────────────────

    async def reset(self, data: dict, context=None):
        try:
            cleared = len(self._specs)
            self._specs = []
            restored = sorted(self._tool_originals.keys())
            for tool_name in restored:
                raw_tool = self._find_raw_tool(tool_name)
                if raw_tool is not None:
                    self._restore_tool(tool_name, raw_tool)
            await self.bus.publish("system.chaos.reset", ChaosResetPayload(cleared=cleared).model_dump())
            return {"success": True, "data": ResetData(cleared=cleared, restored_tools=restored).model_dump()}
        except Exception as e:
            self.logger.error(f"[ChaosControl] reset failed: {e}")
            return {"success": False, "error": "Could not reset chaos state"}

    # ── GET /system/chaos ────────────────────────────────────────────────────

    async def get_state(self, data: dict, context=None):
        try:
            out = ChaosStateData(
                faults=[s.to_view() for s in self._specs],
                wrapped_tools=sorted(self._tool_originals.keys()),
            )
            return {"success": True, "data": out.model_dump()}
        except Exception as e:
            self.logger.error(f"[ChaosControl] get_state failed: {e}")
            return {"success": False, "error": "Could not read chaos state"}

    # ── Tool wrapping machinery (see module docstring) ──────────────────────

    def _find_raw_tool(self, name: str):
        for tool in self.container.get_raw_tools():
            if getattr(tool, "name", None) == name:
                return tool
        return None

    def _resolve_targets(self, tool_name: Optional[str]) -> list[tuple[str, object]]:
        """tool_name given -> that single tool (empty list if unknown).
        tool_name omitted -> every currently-registered tool (honest
        approximation of 'every tool this plugin touches' with zero static
        analysis of the target plugin's source)."""
        if tool_name is not None:
            raw = self._find_raw_tool(tool_name)
            return [(tool_name, raw)] if raw is not None else []
        return [(t.name, t) for t in self.container.get_raw_tools() if getattr(t, "name", None)]

    def _tool_method_names(self, raw_tool) -> list[str]:
        return [
            method_name for method_name, _ in inspect.getmembers(raw_tool, predicate=inspect.isroutine)
            if not method_name.startswith("_") and method_name not in self._IGNORED_TOOL_METHODS
        ]

    def _invalidate_proxy_cache(self, tool_name: str, method_name: str) -> None:
        """See module docstring 'DEVIATION FROM THE LETTER OF THE ROADMAP'."""
        proxy = self.container.get(tool_name)
        cache = getattr(proxy, "_wrapper_cache", None)
        if cache is not None:
            cache.pop(method_name, None)

    def _ensure_wrapped(self, tool_name: str, raw_tool) -> None:
        """Idempotent: wraps each public method with a PERSISTENT dispatcher
        exactly once. Subsequent faults on this tool only mutate self._specs
        — no re-wrapping, no chained closures."""
        if tool_name in self._tool_originals:
            return
        originals = {m: getattr(raw_tool, m) for m in self._tool_method_names(raw_tool)}
        self._tool_originals[tool_name] = originals
        for method_name, original in originals.items():
            setattr(raw_tool, method_name, self._make_dispatcher(tool_name, method_name, original))
            self._invalidate_proxy_cache(tool_name, method_name)

    def _maybe_restore_if_unused(self, tool_name: str, raw_tool) -> None:
        """If no spec targets this tool anymore, restore its true originals
        (keeps 'off'/no-remaining-fault state indistinguishable from never
        having been touched)."""
        if tool_name in self._tool_originals and not any(s.tool == tool_name for s in self._specs):
            self._restore_tool(tool_name, raw_tool)

    def _restore_tool(self, tool_name: str, raw_tool) -> None:
        originals = self._tool_originals.pop(tool_name, None)
        if not originals:
            return
        for method_name, original in originals.items():
            setattr(raw_tool, method_name, original)
            self._invalidate_proxy_cache(tool_name, method_name)

    def _make_dispatcher(self, tool_name: str, method_name: str, original: callable):
        """The ONE wrapper ever installed per (tool, method). Re-reads
        self._specs live on every call — this is what makes composing
        multiple faults, and clearing them, need no re-wrapping."""
        is_async = inspect.iscoroutinefunction(original)
        label = f"{tool_name}.{method_name}"

        def _active_specs():
            return [s for s in self._specs if s.tool == tool_name and s.matches_caller()]

        if is_async:
            async def _dispatch(*args, **kwargs):
                for spec in _active_specs():
                    if spec.mode == "down":
                        raise ChaosToolFaultError(f"Chaos: tool '{label}' is DOWN (chaos injected).")
                    if spec.mode == "flaky" and random.random() < (spec.rate or 0):
                        raise ChaosToolFaultError(f"Chaos: tool '{label}' FLAKY fault injected (rate={spec.rate}).")
                    if spec.mode == "slow":
                        await asyncio.sleep(spec.seconds or 0)
                return await original(*args, **kwargs)
        else:
            def _dispatch(*args, **kwargs):
                for spec in _active_specs():
                    if spec.mode == "down":
                        raise ChaosToolFaultError(f"Chaos: tool '{label}' is DOWN (chaos injected).")
                    if spec.mode == "flaky" and random.random() < (spec.rate or 0):
                        raise ChaosToolFaultError(f"Chaos: tool '{label}' FLAKY fault injected (rate={spec.rate}).")
                    if spec.mode == "slow":
                        time.sleep(spec.seconds or 0)
                return original(*args, **kwargs)

        return _dispatch
