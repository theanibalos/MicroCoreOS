import os
import importlib.util
import inspect
import threading
from core.container import Container
from core.base_tool import BaseTool
from core.base_plugin import BasePlugin

class Kernel:
    # Herramientas fundamentales sin las cuales el sistema no tiene sentido
    REQUIRED_TOOLS = []

    def __init__(self):
        self.container = Container()
        self.plugins = {}

    def _load_modules_from_dir(self, directory, base_class):
        instances = []
        if not os.path.exists(directory): return instances

        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py") and file != "__init__.py":
                    path = os.path.abspath(os.path.join(root, file))
                    module_name = path.replace(os.sep, "_").replace(".", "_")
                    
                    try:
                        spec = importlib.util.spec_from_file_location(module_name, path)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        domain_name = None
                        if directory == "domains":
                            rel_path = os.path.relpath(path, os.path.abspath(directory))
                            parts = rel_path.split(os.sep)
                            if len(parts) >= 1:
                                domain_name = parts[0]

                        for name, obj in inspect.getmembers(module):
                            if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                                instances.append((obj, domain_name))
                                
                        # --- Registro de Modelos (Uso de Registry del Core) ---
                        if domain_name and "models" in path:
                            with open(path, "r", encoding="utf-8") as f:
                                self.container.registry.register_domain_metadata(domain_name, f"model_{file}", f.read())
                                
                    except Exception as e:
                        print(f"[Kernel] 🔥 Error cargando archivo {path}: {e}")
        return instances

    def boot(self):
        print("--- [Kernel] Iniciando Sistema ---")
        
        # 1. Cargar e Iniciar Tools
        for tool_cls, _ in self._load_modules_from_dir("tools", BaseTool):
            try:
                instance = tool_cls()
                instance.setup()
                self.container.register(instance)
                self.container.set_health(instance.name, Container.STATUS_OK)
            except Exception as e:
                tool_name = getattr(tool_cls(), 'name', tool_cls.__name__)
                self.container.set_health(tool_name, Container.STATUS_FAIL, str(e))
                
                if tool_name in self.REQUIRED_TOOLS:
                    print(f"[Kernel] 🚨 CRÍTICO: Herramienta requerida '{tool_name}' falló: {e}")
                else:
                    print(f"[Kernel] ⚠️ Herramienta opcional '{tool_name}' falló: {e}")

        # 2. Cargar e Iniciar Plugins
        plugin_threads = []
        for plugin_cls, domain_name in self._load_modules_from_dir("domains", BasePlugin):
            try:
                sig = inspect.signature(plugin_cls.__init__)
                dependencies = {}
                
                for param_name, _ in sig.parameters.items():
                    if param_name == "self": continue
                    if param_name == "container":
                        dependencies["container"] = self.container
                    elif self.container.has_tool(param_name):
                        dependencies[param_name] = self.container.get(param_name)
                    else:
                        print(f"[Kernel] ⚠️ Warning: Plugin {plugin_cls.__name__} pide '{param_name}' pero no existe.")

                # Notificar al Registry del Core
                self.container.registry.register_plugin(plugin_cls.__name__, {
                    "dependencies": list(dependencies.keys()),
                    "domain": domain_name,
                    "class": plugin_cls.__name__
                })

                instance = plugin_cls(**dependencies)
                
                def boot_plugin_task(plugin_instance, name):
                    try:
                        plugin_instance.on_boot()
                        print(f"[Kernel] Plugin listo: {name}")
                        self.container.registry.update_plugin_status(name, "READY")
                    except BaseException as e:
                        print(f"[Kernel] ⚠️ Fallo CRÍTICO en on_boot del plugin {name}: {repr(e)}")
                        self.container.registry.update_plugin_status(name, "DEAD", str(e))

                t = threading.Thread(target=boot_plugin_task, args=(instance, plugin_cls.__name__), daemon=True)
                t.start()
                plugin_threads.append(t)
                
                self.plugins[plugin_cls.__name__] = instance
                self.container.registry.update_plugin_status(plugin_cls.__name__, "RUNNING")
                print(f"[Kernel] Plugin cargado (DI) y arrancando en hilo: {plugin_cls.__name__}")
            except Exception as e:
                print(f"[Kernel] ⚠️ Fallo al inicializar plugin {plugin_cls.__name__}: {e}")
                self.container.registry.update_plugin_status(plugin_cls.__name__, "DEAD", str(e))

        # Diseño: Boot asíncrono/no-bloqueante.
        # Los plugins se inician en paralelo y no esperamos su término.
        # Esto permite que tengan loops infinitos o tareas de larga duración.

        # 3. Lanzar on_boot_complete
        for tool_name in self.container.list_tools():
            try:
                tool = self.container.get(tool_name)
                tool.on_boot_complete(self.container)
            except Exception as e:
                print(f"[Kernel] Error en on_boot_complete de {tool_name}: {e}")

        print("--- [Kernel] Sistema Listo ---")

    def run_plugin(self, plugin_name, **kwargs):
        if plugin_name not in self.plugins:
            return {"success": False, "error": f"Plugin {plugin_name} no encontrado."}
        try:
            return self.plugins[plugin_name].execute(**kwargs)
        except Exception as e:
            print(f"[Kernel] 💥 Crash en ejecución de {plugin_name}: {e}")
            return {"success": False, "error": "Internal Plugin Error", "details": str(e)}


    def shutdown(self):
        print("\n--- [Kernel] Iniciando apagado de herramientas ---")
        for tool_name in self.container.list_tools():
            try:
                tool = self.container.get(tool_name)
                tool.shutdown()
                print(f"[Kernel] Tool '{tool_name}' cerrada correctamente.")
            except Exception as e:
                print(f"[Kernel] Error cerrando '{tool_name}': {e}")