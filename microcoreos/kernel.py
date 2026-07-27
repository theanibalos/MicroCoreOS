import os
import importlib
import inspect
import asyncio
from microcoreos.container import Container
from microcoreos.base_tool import BaseTool
from microcoreos.base_plugin import BasePlugin
from microcoreos.context import current_identity_var

class Kernel:
    def __init__(self):
        self.container = Container()
        self.plugins = {}

    async def _call_maybe_async(self, func, *args, **kwargs):
        """
        Calls a function and awaits it if it returns a coroutine.
        If it's a synchronous function, it runs it in a separate thread 
        to avoid blocking the main Event Loop.
        """
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        
        # Call it (possibly in thread)
        res = await asyncio.to_thread(func, *args, **kwargs)
        
        # Handle cases where a sync func returns a coroutine (rare but possible with wrappers)
        if inspect.iscoroutine(res):
            return await res
        return res

    def _load_modules_from_dir(self, directory, base_class, suffix):
        """Discovers and instantiates modules from a directory.

        Modules are loaded by their real dotted name via import_module, NOT by
        file path. This matters: path loading builds a private module object, so
        a file the Kernel loaded AND someone imported normally exists twice, with
        two distinct copies of every class it defines — `isinstance` between them
        is False. Importing by name shares one object through sys.modules, so the
        class a plugin imports is the class the Kernel discovered.

        Only files ending in `suffix` are imported — the repo naming convention
        ("_tool.py", "_plugin.py"). Discovery is a side effect of import, so
        importing a file that CANNOT hold a tool is not free: an optional driver
        whose broker library is not installed (redis, aiokafka) would raise at
        import and report a boot error for a transport nobody selected. Helper
        modules split out of a big tool are imported by the tool itself, not here.
        The cost is that a misnamed file is invisible — the devtools linter
        catches that in CI, where a silent miss is cheap to find.
        """
        found_classes = []
        if not os.path.exists(directory):
            return found_classes

        abs_dir = os.path.abspath(directory)
        # Dotted prefix of the scanned dir ("tools", "domains"). Import by name
        # needs the dir reachable from the interpreter's import roots.
        rel_dir = os.path.relpath(abs_dir, os.getcwd())
        if rel_dir.startswith(".."):
            print(f"[Kernel] 🔥 '{directory}' is outside the import root — cannot load.")
            return found_classes
        package = rel_dir.replace(os.sep, ".").strip(".")

        is_domains_dir = os.path.basename(abs_dir) == "domains"
        for root, _, files in os.walk(abs_dir):
            for file in sorted(files):
                if not file.endswith(suffix):
                    continue

                path = os.path.join(root, file)
                relative = os.path.relpath(path, abs_dir)
                module_name = f"{package}.{relative[:-3].replace(os.sep, '.')}"

                try:
                    module = importlib.import_module(module_name)

                    domain_name = None
                    if is_domains_dir:
                        domain_name = relative.split(os.sep)[0]

                    for _, obj in inspect.getmembers(module):
                        if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                            if obj.__module__ == module.__name__:
                                found_classes.append((obj, domain_name))

                except Exception as e:
                    print(f"[Kernel] 🔥 Error loading file {path}: {e}")
        return found_classes

    def _resolve_plugin_dependencies(self, plugin_cls):
        """Resolves dependencies for a plugin using type hints."""
        sig = inspect.signature(plugin_cls.__init__)
        dependencies = {}
        missing = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "args", "kwargs"): continue
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

    async def boot(self):
        print("--- [Kernel] Starting System (Async Engine) ---")

        # 1. Boot Tools — parallel (tools are independent by Rule 2, so setup() is safe to parallelize)
        async def _setup_tool(tool_cls):
            t_name = tool_cls.__name__
            try:
                instance = tool_cls()
                t_name = instance.name
                await self._call_maybe_async(instance.setup)
                self.container.register(instance)
                self.container.registry.register_tool(t_name, "OK")
                print(f"[Kernel] Tool ready: {t_name}")
            except Exception as e:
                self.container.registry.register_tool(t_name, "FAIL", str(e))
                print(f"[Kernel] 🚨 Tool '{t_name}' failed: {e}")

        tool_classes = self._load_modules_from_dir("tools", BaseTool, "_tool.py")
        await asyncio.gather(*[asyncio.create_task(_setup_tool(cls)) for cls, _ in tool_classes])

        # 2. Boot Plugins
        boot_tasks = []
        for plugin_cls, domain in self._load_modules_from_dir("domains", BasePlugin, "_plugin.py"):
            class_name = plugin_cls.__name__
            p_name = f"{domain}.{class_name}" if domain else class_name
            try:
                deps, missing = self._resolve_plugin_dependencies(plugin_cls)
                
                self.container.registry.register_plugin(p_name, {
                    "dependencies": list(deps.keys()),
                    "domain": domain,
                    "class": class_name
                })

                if missing:
                    err = f"Missing tools: {', '.join(missing)}"
                    print(f"[Kernel] 🚨 Plugin {p_name} aborted: {err}")
                    self.container.registry.update_plugin_status(p_name, "DEAD", err)
                    continue

                instance = plugin_cls(**deps)
                # Stamp the registered identity so infrastructure names this
                # plugin exactly like the registry does ("domain.ClassName").
                instance._identity = p_name
                self.plugins[p_name] = instance
                self.container.registry.update_plugin_status(p_name, "RUNNING")

                async def _start(p_inst, name):
                    token = current_identity_var.set(f"{name}.on_boot")
                    try:
                        await self._call_maybe_async(p_inst.on_boot)
                        print(f"[Kernel] Plugin ready: {name}")
                        self.container.registry.update_plugin_status(name, "READY")
                    except Exception as ex:
                        print(f"[Kernel] ⚠️ Failure in {name}: {repr(ex)}")
                        self.container.registry.update_plugin_status(name, "DEAD", str(ex))
                    finally:
                        current_identity_var.reset(token)

                boot_tasks.append(asyncio.create_task(_start(instance, p_name)))
                
            except Exception as e:
                print(f"[Kernel] ⚠️ Initialization error in {p_name}: {e}")
                self.container.registry.update_plugin_status(p_name, "DEAD", str(e))

        # Wait for all plugins to finish booting
        if boot_tasks:
            await asyncio.gather(*boot_tasks)

        # 3. Finalize
        for name in self.container.list_tools():
            try:
                await self._call_maybe_async(self.container.get(name).on_boot_complete, self.container)
            except Exception as e:
                print(f"[Kernel] Post-boot error in {name}: {e}")

        print("--- [Kernel] System Ready ---")

    async def boot_tool(self, tool_name: str):
        """Pipeline entry point: boot ONE tool in isolation, then exit.

        Runs the tool's full lifecycle (setup → on_boot_complete → shutdown)
        with no plugins and no other infrastructure. Deployment pipelines use
        this to trigger a tool's boot-time maintenance work offline; which
        tool and with which env vars is deployment configuration, not code.
        """
        print(f"--- [Kernel] Single-tool boot: '{tool_name}' ---")
        for tool_cls, _ in self._load_modules_from_dir("tools", BaseTool, "_tool.py"):
            instance = tool_cls()
            if instance.name != tool_name:
                continue
            await self._call_maybe_async(instance.setup)
            try:
                await self._call_maybe_async(instance.on_boot_complete, self.container)
            finally:
                await self._call_maybe_async(instance.shutdown)
            print(f"--- [Kernel] '{tool_name}' boot complete ---")
            return
        raise RuntimeError(f"No tool named '{tool_name}' found.")

    async def shutdown(self):
        print("\n--- [Kernel] Shutting down ---")
        for name, instance in self.plugins.items():
            try:
                await self._call_maybe_async(instance.shutdown)
            except Exception as e:
                print(f"[Kernel] Error shutting down plugin '{name}': {e}")
        for name in self.container.list_tools():
            try:
                await self._call_maybe_async(self.container.get(name).shutdown)
                print(f"[Kernel] Tool '{name}' closed.")
            except Exception as e:
                print(f"[Kernel] Error closing '{name}': {e}")