from microcoreos import BaseTool
from microcoreos_dev.lint.checkers.doc_drift import check_tool_doc_drift


class MockDriftTool(BaseTool):
    @property
    def name(self): return "drift_tool"
    async def setup(self): pass
    def get_interface_description(self):
        return "This tool has documented_method"

    def documented_method(self): pass
    def undocumented_method(self): pass


def test_detects_drift():
    findings = check_tool_doc_drift(tools=[MockDriftTool()])
    warnings = [f.message for f in findings]

    assert any("'undocumented_method'" in w for w in warnings)
    assert not any("'documented_method'" in w for w in warnings)


def test_lifecycle_methods_are_never_faulted():
    """setup/shutdown/name & co. are BaseTool plumbing, not capabilities."""
    class BareTool(BaseTool):
        @property
        def name(self): return "bare"
        async def setup(self): pass
        def get_interface_description(self): return "Does nothing."

    findings = check_tool_doc_drift(tools=[BareTool()])
    assert findings == []
