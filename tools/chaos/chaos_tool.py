from core.base_tool import BaseTool

class ChaosTool(BaseTool):
    """
    A tool that intentionally fails during boot to verify that the 
    Kernel survives tool failures.
    """
    @property
    def name(self) -> str:
        return "chaos"

    async def setup(self):
        print("[ChaosTool] 🔥 I am about to explode in 3... 2... 1...")
        raise RuntimeError("BOOM! Tool initialization failed intentionally.")

    def get_interface_description(self) -> str:
        return "This tool is broken by design."
