from core.base_plugin import BasePlugin

class WelcomeLogger(BasePlugin):
    def on_boot(self):
        # Suscribirse al evento nada más arrancar el sistema
        bus = self.container.get("event_bus")
        bus.subscribe("user_created", self.on_user_created)
        print("[Notifications] Suscrito a eventos de usuario.")

    def on_user_created(self, data):
        # Esta función se ejecutará automáticamente cuando el otro plugin publique
        logger = self.container.get("logger")
        logger.info(f"--- EVENTO RECIBIDO ---")
        logger.info(f"Enviando correo de bienvenida a {data['name']} ({data['email']})")

    def execute(self, **kwargs):
        # Este plugin no se llama manualmente, vive de los eventos
        pass