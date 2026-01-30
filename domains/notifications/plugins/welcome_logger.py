from core.base_plugin import BasePlugin

class WelcomeLogger(BasePlugin):
    def __init__(self, event_bus, logger):
        self.bus = event_bus
        self.logger = logger

    def on_boot(self):
        # Suscribirse al evento nada más arrancar el sistema
        self.bus.subscribe("user_created", self.on_user_created)
        print("[Notifications] Suscrito a eventos de usuario.")

    def on_user_created(self, data):
        # Esta función se ejecutará automáticamente cuando el otro plugin publique
        self.logger.info(f"--- EVENTO RECIBIDO ---")
        self.logger.info(f"Enviando correo de bienvenida a {data['name']} ({data['email']})")

    def execute(self, **kwargs):
        # Este plugin no se llama manualmente, vive de los eventos
        pass