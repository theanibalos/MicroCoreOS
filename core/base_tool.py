from abc import ABC, abstractmethod

class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """El identificador único (ej: 'db', 'auth', 'storage')"""
        pass

    @abstractmethod
    def setup(self):
        """Aquí se inicializa la conexión o configuración"""
        pass

    @abstractmethod
    def get_interface_description(self) -> str:
        """
        Retorna una descripción de sus métodos disponibles.
        Este es el 'manual' que leerá la IA para saber qué puede usar.
        """
        pass