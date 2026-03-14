import os
import contextlib
from core.base_tool import BaseTool


class _NoOpTracer:
    """Fallback tracer returned when OTel is disabled or not installed."""
    def start_as_current_span(self, name, **kwargs):
        return contextlib.nullcontext()


class TelemetryTool(BaseTool):
    """
    OpenTelemetry distributed tracing tool for MicroCoreOS.

    Auto-instruments ALL tool calls via ToolProxy — no changes needed in plugins or tools.
    Optionally instruments underlying frameworks (FastAPI, asyncpg) via on_instrument() hooks.

    Activation: set OTEL_ENABLED=true in environment.
    Degrades gracefully if disabled or if opentelemetry packages are not installed.
    """

    @property
    def name(self) -> str:
        return "telemetry"

    async def setup(self):
        self._tracer_provider = None
        self._enabled = os.getenv("OTEL_ENABLED", "false").lower() == "true"

        if not self._enabled:
            print("[TelemetryTool] Disabled. Set OTEL_ENABLED=true to activate.")
            return

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.resources import Resource

            service_name = os.getenv("OTEL_SERVICE_NAME", "microcoreos")
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)

            if endpoint:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
                print(f"[TelemetryTool] Exporting to {endpoint} (service: {service_name})")
            else:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
                print(f"[TelemetryTool] Console exporter active (service: {service_name}). "
                      "Set OTEL_EXPORTER_OTLP_ENDPOINT for production.")

            trace.set_tracer_provider(provider)
            self._tracer_provider = provider

        except ImportError as e:
            print(f"[TelemetryTool] WARNING: OTEL_ENABLED=true but packages missing: {e}")
            print("[TelemetryTool] Install: uv add opentelemetry-sdk opentelemetry-exporter-otlp")
            self._enabled = False

    async def on_boot_complete(self, container):
        if not self._enabled or not self._tracer_provider:
            return

        # 1. Register span factory — all future tool calls get a span automatically.
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer("microcoreos.proxy")

            def span_factory(tool: str, method: str):
                return tracer.start_as_current_span(
                    f"{tool}.{method}",
                    attributes={"tool": tool, "method": method},
                )

            container.register_span_factory(span_factory)
        except Exception as e:
            print(f"[TelemetryTool] Failed to register span factory: {e}")
            return

        # 2. Call on_instrument() on each raw tool instance for driver-level spans.
        #    Runs bypassing ToolProxy so a failure here never marks a tool as DEAD.
        for raw_tool in container.get_raw_tools():
            if raw_tool.name == self.name:
                continue
            try:
                await raw_tool.on_instrument(self._tracer_provider)
            except Exception as e:
                print(f"[TelemetryTool] on_instrument() failed for '{raw_tool.name}': {e}")

    def get_tracer(self, scope: str):
        """Get a named tracer for custom spans inside a plugin.
        Returns a no-op tracer if OTel is disabled.

        Usage:
            tracer = self.telemetry.get_tracer("orders")
            with tracer.start_as_current_span("process_payment"):
                ...
        """
        if not self._enabled:
            return _NoOpTracer()
        try:
            from opentelemetry import trace
            return trace.get_tracer(scope)
        except ImportError:
            return _NoOpTracer()

    async def shutdown(self):
        if self._tracer_provider:
            try:
                self._tracer_provider.shutdown()
            except Exception:
                pass

    def get_interface_description(self) -> str:
        return """
        Telemetry Tool (telemetry):
        - PURPOSE: OpenTelemetry distributed tracing. Auto-instruments all tool calls via ToolProxy.
          No changes needed in plugins or existing tools to get basic spans.
        - ACTIVATION: Set OTEL_ENABLED=true. Degrades gracefully if disabled or packages missing.
        - ENV VARS:
            - OTEL_ENABLED: "true" to activate (default: "false").
            - OTEL_SERVICE_NAME: Service name in traces (default: "microcoreos").
            - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP/gRPC endpoint (e.g. "http://jaeger:4317").
              If not set, traces are printed to console (development mode).
        - CAPABILITIES:
            - get_tracer(scope: str) -> Tracer: Named tracer for custom spans inside a plugin.
                Usage: tracer = self.telemetry.get_tracer("my_plugin")
                       with tracer.start_as_current_span("my_operation"): ...
                Returns a no-op tracer if OTel is disabled — safe to use unconditionally.
        - AUTO-INSTRUMENTATION (zero config):
            Every tool call (db.execute, event_bus.publish, auth.create_token, etc.)
            gets a span automatically via ToolProxy. No plugin changes needed.
        - DRIVER-LEVEL INSTRUMENTATION (optional, per tool):
            Tools can implement on_instrument(tracer_provider) in BaseTool to add
            framework-specific spans (SQL query text, HTTP route, etc.).
        - INSTALL:
            uv add opentelemetry-sdk opentelemetry-exporter-otlp
        """
