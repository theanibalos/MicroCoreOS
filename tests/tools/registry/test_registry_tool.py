from tools.system.registry_tool import RegistryTool
from microcoreos.container import Container


def test_registry_tool_uninitialized():
    tool = RegistryTool()
    assert tool.name == "registry"
    tool.setup()

    assert tool.get_system_dump() == {"tools": {}, "domains": {}, "plugins": {}}
    assert tool.get_domain_metadata() == {}
    assert tool.get_metrics() == []
    
    # Should not raise when container/core_registry are None
    tool.add_metrics_sink(lambda r: None)
    tool.update_tool_status("my_tool", "DEAD", "error")

    desc = tool.get_interface_description()
    assert "Systems Registry Tool" in desc


def test_registry_tool_initialized_via_container():
    container = Container()
    tool = RegistryTool()

    container.register(tool)

    # Verify container automatically called _set_core_registry and _set_container
    assert tool._core_registry is container.registry
    assert tool._container is container

    # Test update_tool_status on registered tool
    container.registry.register_tool("registry", "OK")
    tool.update_tool_status("registry", "FAIL", "overridden")
    assert container.registry.get_tool_status("registry") == "FAIL"

    # Test get_system_dump
    dump = tool.get_system_dump()
    assert "tools" in dump
    assert "registry" in dump["tools"]

    # Test get_domain_metadata
    meta = tool.get_domain_metadata()
    assert isinstance(meta, dict)

    # Test get_metrics & add_metrics_sink
    metrics = tool.get_metrics()
    assert isinstance(metrics, list)

    sinks = []
    tool.add_metrics_sink(lambda record: sinks.append(record))
    assert len(container._metrics_sinks) == 1
