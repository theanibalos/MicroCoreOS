import os
import importlib.util
import inspect
from core.container import Container
from core.base_tool import BaseTool
from core.base_plugin import BasePlugin

class Kernel:
    def __init__(self):
        self.container = Container()
        self.plugins = {}

    def _load_modules_from_dir(self, directory, base_class):
        """
        Busca archivos .py en un directorio e instancia clases 
        que hereden de base_class.
        """
        instances = []
        if not os.path.exists(directory):
            return instances

        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py") and file != "__init__.py":
                    path = os.path.join(root, file)
                    module_name = file[:-3]
                    
                    # Carga dinámica del archivo
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Buscar clases que hereden de la base (pero que no sean la base misma)
                    for name, obj in inspect.getmembers(module):
                        if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                            instances.append(obj)
        return instances

    def boot(self):
        """Ciclo de vida de arranque"""
        print("--- [Kernel] Iniciando Sistema ---")
        
        # 1. Cargar Tools
        tool_classes = self._load_modules_from_dir("tools", BaseTool)
        for tool_cls in tool_classes:
            tool_instance = tool_cls()
            tool_instance.setup() # Fase de setup de la tool
            self.container.register(tool_instance)

        # 2. Cargar Plugins (Casos de uso)
        # Buscamos en domains/*/plugins
        plugin_classes = self._load_modules_from_dir("domains", BasePlugin)
        for plugin_cls in plugin_classes:
            # Inyección de dependencia: Pasamos el container al plugin
            plugin_instance = plugin_cls(self.container)
            # Inicializar plugins
            plugin_instance.on_boot()
            # El nombre del plugin suele ser el nombre de la clase o un atributo
            self.plugins[plugin_cls.__name__] = plugin_instance
            print(f"[Kernel] Plugin cargado: {plugin_cls.__name__}")

        print("--- [Kernel] Sistema Listo ---")

    def run_plugin(self, plugin_name, **kwargs):
        """Ejecuta un caso de uso específico"""
        if plugin_name not in self.plugins:
            raise Exception(f"Plugin {plugin_name} no encontrado.")
        return self.plugins[plugin_name].execute(**kwargs)
    
    