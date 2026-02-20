import os
import importlib.util
import inspect
import threading
from core.container import Container
from core.base_tool import BaseTool
from core.base_plugin import BasePlugin

class Kernel:
    def __init__(self):
        self.container = Container()
        self.plugins = {}

    def _load_modules_from_dir(self, directory, base_class):
        """Discovers and instantiates modules of a given base_class inside a directory."""
        instances = []
        if not os.path.exists(directory): 
            return instances

        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py") and file != "__init__.py":
                    path = os.path.abspath(os.path.join(root, file))
                    module_name = path.replace(os.sep, "_").replace(".", "_")
                    
                    try:
                        spec = importlib.util.spec_from_file_location(module_name, path)
                        module = importlib.util.module_from_spec(spec)
                        if spec.loader:
                            spec.loader.exec_module(module)

                        # Determine Domain Name for models and plugins
                        domain_name = None
                        if directory == "domains":
                            rel_path = os.path.relpath(path, os.path.abspath(directory))
                            parts = rel_path.split(os.sep)
                            if len(parts) >= 1:
                                domain_name = parts[0]

                        # Register Domain Models
                        if domain_name and "models" in path:
                            with open(path, "r", encoding="utf-8") as f:
                                self.container.registry.register_domain_metadata(domain_name, f"model_{file}", f.read())

                        # Discover classes
                        for _, obj in inspect.getmembers(module):
                            if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                                if obj.__module__ == module.__name__:
                                    instances.append((obj, domain_name))

                    except Exception as e:
                        print(f"[Kernel] 🔥 Error loading file {path}: {e}")
        return instances

    def _resolve_plugin_dependencies(self, plugin_cls):
        """Resolves dependencies for a plugin using type hints and default values from its __init__ signature."""
        sig = inspect.signature(plugin_cls.__init__)
        dependencies = {}
        missing_requirements = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "args", "kwargs"): 
                continue
            
            # Inject Container natively
            if param_name == "container":
                dependencies["container"] = self.container
                continue
                
            is_required = param.default == inspect.Parameter.empty
            
            if self.container.has_tool(param_name):
                dependencies[param_name] = self.container.get(param_name)
            else:
                if is_required:
                    missing_requirements.append(param_name)
                else:
                    dependencies[param_name] = param.default
                    print(f"[Kernel] ℹ️ Plugin {plugin_cls.__name__}: Optional tool '{param_name}' not found, injected default: {param.default}.")
                    
        return dependencies, missing_requirements

    def boot(self):
        print("--- [Kernel] Starting System ---")
        
        # 1. Load and Initialize Tools
        for tool_cls, _ in self._load_modules_from_dir("tools", BaseTool):
            try:
                instance = tool_cls()
                instance.setup()
                self.container.register(instance)
                self.container.set_health(instance.name, Container.STATUS_OK)
            except Exception as e:
                tool_name = getattr(tool_cls(), 'name', tool_cls.__name__)
                self.container.set_health(tool_name, Container.STATUS_FAIL, str(e))
                print(f"[Kernel] 🚨 CRITICAL: Tool '{tool_name}' failed to initialize: {e}")

        # 2. Load and Initialize Plugins
        for plugin_cls, domain_name in self._load_modules_from_dir("domains", BasePlugin):
            try:
                # Resolve dependencies recursively or using container
                dependencies, missing_requirements = self._resolve_plugin_dependencies(plugin_cls)

                if missing_requirements:
                    print(f"[Kernel] 🚨 CRITICAL: Plugin {plugin_cls.__name__} aborted. Missing required tools: {', '.join(missing_requirements)}")
                    self.container.registry.register_plugin(plugin_cls.__name__, {
                        "dependencies": [],
                        "domain": domain_name,
                        "class": plugin_cls.__name__
                    })
                    self.container.registry.update_plugin_status(plugin_cls.__name__, "DEAD", f"Missing tools: {', '.join(missing_requirements)}")
                    continue

                # Register Plugin Meta
                self.container.registry.register_plugin(plugin_cls.__name__, {
                    "dependencies": list(dependencies.keys()),
                    "domain": domain_name,
                    "class": plugin_cls.__name__
                })

                # Instantiate Plugin
                instance = plugin_cls(**dependencies)
                
                # Boot Plugin Thread
                def boot_plugin_task(plugin_instance, name):
                    try:
                        plugin_instance.on_boot()
                        print(f"[Kernel] Plugin ready: {name}")
                        self.container.registry.update_plugin_status(name, "READY")
                    except BaseException as e:
                        print(f"[Kernel] ⚠️ CRITICAL failure in on_boot of plugin {name}: {repr(e)}")
                        self.container.registry.update_plugin_status(name, "DEAD", str(e))

                t = threading.Thread(target=boot_plugin_task, args=(instance, plugin_cls.__name__), daemon=True)
                t.start()
                
                # Save Reference
                self.plugins[plugin_cls.__name__] = instance
                self.container.registry.update_plugin_status(plugin_cls.__name__, "RUNNING")
                
                print(f"[Kernel] Plugin loaded (DI) and starting task: {plugin_cls.__name__}")
                
            except Exception as e:
                print(f"[Kernel] ⚠️ Failed to initialize plugin {plugin_cls.__name__}: {e}")
                self.container.registry.update_plugin_status(plugin_cls.__name__, "DEAD", str(e))

        # 3. Trigger Post-Boot Hooks (on_boot_complete)
        for tool_name in self.container.list_tools():
            try:
                tool = self.container.get(tool_name)
                tool.on_boot_complete(self.container)
            except Exception as e:
                print(f"[Kernel] Error in on_boot_complete of {tool_name}: {e}")

        print("--- [Kernel] System Ready ---")

    def run_plugin(self, plugin_name, **kwargs):
        """Synchronously execute a plugin method by name (Usually for debugging or direct commands)"""
        if plugin_name not in self.plugins:
            return {"success": False, "error": f"Plugin {plugin_name} not found."}
        try:
            return self.plugins[plugin_name].execute(**kwargs)
        except Exception as e:
            print(f"[Kernel] 💥 Crash in execution of {plugin_name}: {e}")
            return {"success": False, "error": "Internal Plugin Error", "details": str(e)}

    def shutdown(self):
        """Gracefully shut down all tools"""
        print("\n--- [Kernel] Shutting down tools ---")
        for tool_name in self.container.list_tools():
            try:
                tool = self.container.get(tool_name)
                tool.shutdown()
                print(f"[Kernel] Tool '{tool_name}' closed successfully.")
            except Exception as e:
                print(f"[Kernel] Error closing '{tool_name}': {e}")