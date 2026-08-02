import sys
import types
import pytest
from unittest.mock import MagicMock, AsyncMock
from microcoreos.container import Container
from tools.telemetry.telemetry_tool import TelemetryTool, _NoOpTracer


@pytest.mark.anyio
async def test_noop_tracer():
    tracer = _NoOpTracer()
    with tracer.start_as_current_span("test_span") as span:
        assert span is None


@pytest.mark.anyio
async def test_telemetry_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    tool = TelemetryTool()
    assert tool.name == "telemetry"
    await tool.setup()
    assert tool._enabled is False
    assert tool._tracer_provider is None

    # Test get_tracer returns _NoOpTracer when disabled
    tracer = tool.get_tracer("test_scope")
    assert isinstance(tracer, _NoOpTracer)

    # Test on_boot_complete does nothing when disabled
    container = MagicMock(spec=Container)
    await tool.on_boot_complete(container)
    container.register_span_factory.assert_not_called()

    # Test shutdown does nothing when _tracer_provider is None
    await tool.shutdown()

    # Test interface description
    desc = tool.get_interface_description()
    assert "Telemetry Tool" in desc


@pytest.mark.anyio
async def test_telemetry_enabled_package_missing(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    tool = TelemetryTool()

    # Hide opentelemetry if it happens to exist
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    await tool.setup()
    assert tool._enabled is False

    tracer = tool.get_tracer("test_scope")
    assert isinstance(tracer, _NoOpTracer)


@pytest.mark.anyio
async def test_telemetry_enabled_console_exporter(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_SERVICE_NAME", "test-service")

    # Build fake opentelemetry module hierarchy
    mock_trace = MagicMock()
    mock_sdk_trace = MagicMock()
    mock_sdk_resources = MagicMock()
    mock_export = MagicMock()

    mock_opentelemetry = types.ModuleType("opentelemetry")
    mock_opentelemetry.trace = mock_trace

    mock_sdk = types.ModuleType("opentelemetry.sdk")
    mock_sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
    mock_sdk_trace_mod.TracerProvider = mock_sdk_trace.TracerProvider

    mock_sdk_res_mod = types.ModuleType("opentelemetry.sdk.resources")
    mock_sdk_res_mod.Resource = mock_sdk_resources.Resource

    mock_sdk_export_mod = types.ModuleType("opentelemetry.sdk.trace.export")
    mock_sdk_export_mod.ConsoleSpanExporter = mock_export.ConsoleSpanExporter
    mock_sdk_export_mod.SimpleSpanProcessor = mock_export.SimpleSpanProcessor

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_opentelemetry)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk", mock_sdk)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", mock_sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", mock_sdk_res_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", mock_sdk_export_mod)

    tool = TelemetryTool()
    await tool.setup()

    assert tool._enabled is True
    assert tool._tracer_provider is not None
    mock_trace.set_tracer_provider.assert_called_once()

    # Test get_tracer when enabled
    mock_trace.get_tracer.return_value = "fake_tracer"
    tracer = tool.get_tracer("my_scope")
    assert tracer == "fake_tracer"
    mock_trace.get_tracer.assert_called_with("my_scope")


@pytest.mark.anyio
async def test_telemetry_enabled_otlp_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    mock_trace = MagicMock()
    mock_sdk_trace = MagicMock()
    mock_sdk_resources = MagicMock()
    mock_otlp = MagicMock()
    mock_export = MagicMock()

    mock_opentelemetry = types.ModuleType("opentelemetry")
    mock_opentelemetry.trace = mock_trace

    mock_sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
    mock_sdk_trace_mod.TracerProvider = mock_sdk_trace.TracerProvider

    mock_sdk_res_mod = types.ModuleType("opentelemetry.sdk.resources")
    mock_sdk_res_mod.Resource = mock_sdk_resources.Resource

    mock_otlp_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    mock_otlp_mod.OTLPSpanExporter = mock_otlp.OTLPSpanExporter

    mock_export_mod = types.ModuleType("opentelemetry.sdk.trace.export")
    mock_export_mod.BatchSpanProcessor = mock_export.BatchSpanProcessor

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_opentelemetry)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", mock_sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", mock_sdk_res_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", mock_otlp_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", mock_export_mod)

    tool = TelemetryTool()
    await tool.setup()
    assert tool._enabled is True


@pytest.mark.anyio
async def test_telemetry_on_boot_complete_and_shutdown(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")

    mock_trace = MagicMock()
    mock_tracer = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer

    mock_opentelemetry = types.ModuleType("opentelemetry")
    mock_opentelemetry.trace = mock_trace

    mock_provider = MagicMock()
    mock_sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
    mock_sdk_trace_mod.TracerProvider = MagicMock(return_value=mock_provider)

    mock_sdk_res_mod = types.ModuleType("opentelemetry.sdk.resources")
    mock_sdk_res_mod.Resource = MagicMock()

    mock_export_mod = types.ModuleType("opentelemetry.sdk.trace.export")
    mock_export_mod.ConsoleSpanExporter = MagicMock()
    mock_export_mod.SimpleSpanProcessor = MagicMock()

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_opentelemetry)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", mock_sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", mock_sdk_res_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", mock_export_mod)

    tool = TelemetryTool()
    await tool.setup()

    # Mock container and raw tools
    registered_factory = []
    container = MagicMock()
    container.register_span_factory = lambda fn: registered_factory.append(fn)

    # Tool A (normal), Tool B (telemetry tool itself, should be skipped), Tool C (raises in on_instrument)
    raw_tool_a = MagicMock()
    raw_tool_a.name = "tool_a"
    raw_tool_a.on_instrument = AsyncMock()

    raw_tool_telemetry = MagicMock()
    raw_tool_telemetry.name = "telemetry"

    raw_tool_c = MagicMock()
    raw_tool_c.name = "tool_c"
    raw_tool_c.on_instrument = AsyncMock(side_effect=RuntimeError("instrument error"))

    container.get_raw_tools.return_value = [raw_tool_a, raw_tool_telemetry, raw_tool_c]

    await tool.on_boot_complete(container)

    assert len(registered_factory) == 1
    span_fn = registered_factory[0]
    span_fn("db", "query")
    mock_tracer.start_as_current_span.assert_called_with(
        "db.query",
        attributes={"tool": "db", "method": "query"}
    )

    raw_tool_a.on_instrument.assert_called_once_with(tool._tracer_provider)
    raw_tool_c.on_instrument.assert_called_once_with(tool._tracer_provider)

    # Test shutdown
    await tool.shutdown()
    mock_provider.shutdown.assert_called_once()

    # Test shutdown exception swallowing
    mock_provider.shutdown.side_effect = Exception("shutdown error")
    await tool.shutdown()  # should not raise


@pytest.mark.anyio
async def test_telemetry_on_boot_complete_span_factory_failure(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")

    mock_opentelemetry = types.ModuleType("opentelemetry")
    mock_opentelemetry.trace = MagicMock(side_effect=Exception("trace error"))

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_opentelemetry)

    tool = TelemetryTool()
    tool._enabled = True
    tool._tracer_provider = MagicMock()

    container = MagicMock()
    container.register_span_factory.side_effect = Exception("factory fail")

    # Should gracefully catch error without throwing
    await tool.on_boot_complete(container)


@pytest.mark.anyio
async def test_telemetry_get_tracer_import_error(monkeypatch):
    tool = TelemetryTool()
    tool._enabled = True

    mock_opentelemetry = types.ModuleType("opentelemetry")
    mock_trace = MagicMock()
    mock_trace.get_tracer.side_effect = ImportError("opentelemetry trace unavailable")
    mock_opentelemetry.trace = mock_trace
    monkeypatch.setitem(sys.modules, "opentelemetry", mock_opentelemetry)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)

    tracer = tool.get_tracer("my_scope")
    assert isinstance(tracer, _NoOpTracer)
