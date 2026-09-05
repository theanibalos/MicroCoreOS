from unittest.mock import MagicMock
from microcoreos import BaseTool
from tools.context.renderers import _generate_tool_signatures
from tools.context.context_tool import ContextTool


class SampleTool(BaseTool):
    @property
    def name(self):
        return "sample"

    async def setup(self):
        pass

    def get_interface_description(self):
        return "Sample tool interface description"

    # Public methods
    async def fetch_item(self, item_id: int, timeout: float = 5.0) -> dict:
        return {"id": item_id}

    def configure(self, key: str, *, required: bool = True, default_value: str = "val") -> None:
        pass

    # Private method — must be excluded
    def _internal_helper(self):
        pass

    # Lifecycle / ignored plumbing — must be excluded
    def shutdown(self):
        pass


def test_derives_canonical_public_signatures():
    tool = SampleTool()
    sigs = _generate_tool_signatures(tool)

    # Required & default params, async vs sync, types
    assert "async def fetch_item(item_id: int, timeout: float = 5.0) -> dict" in sigs
    assert "def configure(key: str, *, required: bool = True, default_value: str = 'val') -> None" in sigs

    # Private and lifecycle methods must NOT appear
    assert "_internal_helper" not in sigs
    assert "def shutdown" not in sigs
    assert "def setup" not in sigs
    assert "get_interface_description" not in sigs


def test_changed_parameters_update_signatures():
    class DynamicTool(BaseTool):
        @property
        def name(self):
            return "dynamic"

        def setup(self):
            pass

        def get_interface_description(self):
            return "Dynamic tool"

        def compute(self, x: int) -> int:
            return x

    tool = DynamicTool()
    sigs_v1 = _generate_tool_signatures(tool)
    assert "def compute(x: int) -> int" in sigs_v1

    # Modify signature (e.g. new default param, keyword-only)
    class DynamicToolV2(BaseTool):
        @property
        def name(self):
            return "dynamic"

        def setup(self):
            pass

        def get_interface_description(self):
            return "Dynamic tool"

        def compute(self, x: int, multiplier: int = 2, *, precision: int = 4) -> float:
            return float(x * multiplier)

    tool_v2 = DynamicToolV2()
    sigs_v2 = _generate_tool_signatures(tool_v2)
    assert "def compute(x: int, multiplier: int = 2, *, precision: int = 4) -> float" in sigs_v2
    assert sigs_v1 != sigs_v2


def test_removed_methods_disappear():
    class Version1(BaseTool):
        @property
        def name(self):
            return "v"

        def setup(self):
            pass

        def get_interface_description(self):
            return "v"

        def method_a(self):
            pass

        def method_b(self):
            pass

    class Version2(BaseTool):
        @property
        def name(self):
            return "v"

        def setup(self):
            pass

        def get_interface_description(self):
            return "v"

        def method_b(self):
            pass

    sigs_v1 = _generate_tool_signatures(Version1())
    assert "method_a" in sigs_v1
    assert "method_b" in sigs_v1

    sigs_v2 = _generate_tool_signatures(Version2())
    assert "method_a" not in sigs_v2
    assert "method_b" in sigs_v2


def test_opaque_callables_report_unavailable_signature():
    class OpaqueTool(BaseTool):
        @property
        def name(self):
            return "opaque"

        def setup(self):
            pass

        def get_interface_description(self):
            return "opaque"

    tool = OpaqueTool()
    # Built-in or C-function where inspect.signature raises ValueError
    # e.g., object.__subclasshook__ or a mock raising ValueError
    opaque_mock = MagicMock(spec=lambda: None)
    del opaque_mock.__wrapped__

    # Attach an opaque callable
    tool.opaque_method = object().__str__  # inspect.signature works or raises

    class BuiltinOpaque(BaseTool):
        @property
        def name(self):
            return "opaque"

        def setup(self):
            pass

        def get_interface_description(self):
            return "opaque"

    t = BuiltinOpaque()
    # Builtin methods without inspectable signature:
    # We simulate an opaque callable by setting a callable whose inspect.signature fails
    from unittest.mock import patch
    import inspect

    original_sig = inspect.signature

    def mock_sig(func, *args, **kwargs):
        if getattr(func, "__name__", "") == "opaque_call":
            raise ValueError("no signature found for builtin")
        return original_sig(func, *args, **kwargs)

    def opaque_call(self):
        pass

    BuiltinOpaque.opaque_call = opaque_call

    with patch("inspect.signature", side_effect=mock_sig):
        sigs = _generate_tool_signatures(t)

    assert "def opaque_call(...) -> <signature unavailable>" in sigs


def test_manifest_generation_includes_public_signatures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context_tool = ContextTool()

    tool = SampleTool()
    proxy = MagicMock()
    proxy._tool = tool
    proxy.get_interface_description.return_value = tool.get_interface_description()

    container = MagicMock()
    container.list_tools.return_value = ["sample"]
    container.get.return_value = proxy
    container.registry.get_system_dump.return_value = {"plugins": {}}

    context_tool._generate_global_manifest(container, {})

    manifest = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "### 🔧 Tool: `sample` (Status: ✅)" in manifest
    assert "**Public Signatures:**" in manifest
    assert "async def fetch_item(item_id: int, timeout: float = 5.0) -> dict" in manifest
    assert "def configure(key: str, *, required: bool = True, default_value: str = 'val') -> None" in manifest
    assert "Sample tool interface description" in manifest
