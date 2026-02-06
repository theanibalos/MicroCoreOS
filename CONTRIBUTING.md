# Contributing to MicroCoreOS

First off, thank you for considering contributing to MicroCoreOS! 🎉

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues. When you create a bug report, include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples**
- **Describe the behavior you observed and what you expected**
- **Include your Python version and OS**

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a detailed description of the proposed feature**
- **Explain why this enhancement would be useful**
- **List some examples of how it would be used**

### Pull Requests

1. Fork the repo and create your branch from `main`
2. Follow the existing code style
3. Make sure your code follows MicroCoreOS principles:
   - Tools are stateless and cross-domain
   - Plugins are domain-specific and contain business logic
   - No direct plugin-to-plugin calls (use EventBus)
4. Test your changes
5. Update documentation if needed
6. Submit the PR with a clear description

## Code Style

- Follow PEP 8 for Python code
- Keep plugins simple and focused (ideally <100 lines)
- Use type hints where applicable
- Add docstrings to public methods

## Plugin Guidelines

When creating a new plugin:

```python
from core.base_plugin import BasePlugin

class YourPlugin(BasePlugin):
    def __init__(self, tool1, tool2):  # Declare dependencies
        self.tool1 = tool1
        self.tool2 = tool2
    
    def on_boot(self):
        # Register endpoints, subscribe to events
        pass
    
    def execute(self, **kwargs):
        # Your business logic here
        pass
```

## Tool Guidelines

When creating a new tool:

```python
from core.base_tool import BaseTool

class YourTool(BaseTool):
    @property
    def name(self) -> str:
        return "your_tool_name"
    
    def setup(self):
        # Initialize your tool
        pass
    
    def get_interface_description(self) -> str:
        return "Description of what your tool does"
```

## Questions?

Feel free to open an issue with the `question` label or reach out to [@theanibalos](https://twitter.com/theanibalos)

Thank you! 🚀
