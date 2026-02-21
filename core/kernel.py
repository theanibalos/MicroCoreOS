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
        found_classes = []
        if not os.path.exists(directory): 
            return found_classes

        abs_dir = os.path.abspath(directory)
        for root, _, files in os.walk(abs_dir):
            for file in files:
                if not file.endswith(".py") or file == "__init__.py":
                    continue
                
                path = os.path.join(root, file)
                module_name = f"mod_{os.path.relpath(path, abs_dir).replace(os.sep, '_').replace('.', '_')}"
                
                try:
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    module = importlib.util.module_from_spec(spec)
                    if spec.loader:
                        spec.loader.exec_module(module)

                    # Extract metadata if it's a domain
                    domain_name = None
                    if "domains" in path:
                        domain_name = os.path.relpath(path, abs_dir).split(os.sep)[0]

                    # Register models content if found
                    if domain_name and "models" in path:
                        with open(path, "r", encoding="utf-8") as f:
                            self.container.registry.register_domain_metadata(domain_name, f"model_{file}", f.read())

                    for _, obj in inspect.getmembers(module):
                        if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                            if obj.__module__ == module.__name__:
                                found_classes.append((obj, domain_name))

                except Exception as e:
                    print(f"[Kernel] 🔥 Error loading file {path}: {e}")
        return found_classes

    def _resolve_plugin_dependencies(self, plugin_cls):
        """Resolves dependencies for a plugin using type hints and default values."""
        sig = inspect.signature(plugin_cls.__init__)
        dependencies = {}
        missing = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "args", "kwargs"): 
                continue
            
            if param_name == "container":
                dependencies["container"] = self.container
                continue
                
            if self.container.has_tool(param_name):
                dependencies[param_name] = self.container.get(param_name)
            elif param.default == inspect.Parameter.empty:
                missing.append(param_name)
            else:
                dependencies[param_name] = param.default
                    
        return dependencies, missing

    def boot(self):
        print("--- [Kernel] Starting System ---")
        
        # 1. Boot Tools
        for tool_cls, _ in self._load_modules_from_dir("tools", BaseTool):
            try:
                instance = tool_cls()
                t_name = instance.name
                instance.setup()
                self.container.register(instance)
                self.container.registry.register_tool(t_name, "OK")
            except Exception as e:
                # Capture name without full instantiation if possible
                t_name = getattr(tool_cls, 'name', tool_cls.__name__)
                self.container.registry.register_tool(t_name, "FAIL", str(e))
                print(f"[Kernel] 🚨 Tool '{t_name}' failed: {e}")

        # 2. Boot Plugins
        for plugin_cls, domain in self._load_modules_from_dir("domains", BasePlugin):
            p_name = plugin_cls.__name__
            try:
                deps, missing = self._resolve_plugin_dependencies(plugin_cls)
                
                self.container.registry.register_plugin(p_name, {
                    "dependencies": list(deps.keys()),
                    "domain": domain,
                    "class": p_name
                })

                if missing:
                    err = f"Missing tools: {', '.join(missing)}"
                    print(f"[Kernel] 🚨 Plugin {p_name} aborted: {err}")
                    self.container.registry.update_plugin_status(p_name, "DEAD", err)
                    continue

                instance = plugin_cls(**deps)
                self.plugins[p_name] = instance
                self.container.registry.update_plugin_status(p_name, "RUNNING")

                def _start(p_inst, name):
                    try:
                        p_inst.on_boot()
                        print(f"[Kernel] Plugin ready: {name}")
                        self.container.registry.update_plugin_status(name, "READY")
                    except Exception as ex:
                        print(f"[Kernel] ⚠️ Failure in {name}: {repr(ex)}")
                        self.container.registry.update_plugin_status(name, "DEAD", str(ex))

                threading.Thread(target=_start, args=(instance, p_name), daemon=True).start()
                print(f"[Kernel] Plugin loaded (DI) and starting task: {p_name}")
                
            except Exception as e:
                print(f"[Kernel] ⚠️ Initialization error in {p_name}: {e}")
                self.container.registry.update_plugin_status(p_name, "DEAD", str(e))

        # 3. Finalize
        for name in self.container.list_tools():
            try:
                self.container.get(name).on_boot_complete(self.container)
            except Exception as e:
                print(f"[Kernel] Post-boot error in {name}: {e}")

        print("--- [Kernel] System Ready ---")

    def run_plugin(self, plugin_name, **kwargs):
        if plugin_name not in self.plugins:
            return {"success": False, "error": f"Plugin {plugin_name} not found."}
        try:
            return self.plugins[plugin_name].execute(**kwargs)
        except Exception as e:
            print(f"[Kernel] 💥 Crash in {plugin_name}: {e}")
            return {"success": False, "error": str(e)}

    def shutdown(self):
        print("\n--- [Kernel] Shutting down tools ---")
        for name in self.container.list_tools():
            try:
                self.container.get(name).shutdown()
                print(f"[Kernel] Tool '{name}' closed.")
            except Exception as e:
                print(f"[Kernel] Error closing '{name}': {e}")