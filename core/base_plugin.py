from abc import ABC, abstractmethod

class BasePlugin(ABC):
    def __init__(self, container):
        self.container = container

    def on_boot(self):
        """
        Opcional: Se ejecuta al cargar el plugin. 
        Ideal para suscribirse a eventos.
        """
        pass

    @abstractmethod
    def execute(self, **kwargs):
        pass