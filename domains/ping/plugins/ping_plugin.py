from core.base_plugin import BasePlugin
from domains.ping.models.ping_model import PingResponse

class PingPlugin(BasePlugin):
    """
    A simple health-check plugin to verify the MicroCoreOS kernel is alive.
    """
    def __init__(self, logger, http):
        self.logger = logger
        self.http = http

    def on_boot(self):
        self.http.add_endpoint(
            path="/ping",
            method="GET",
            handler=self.handler,
            response_model=PingResponse,
            tags=["System"]
        )

    def execute(self, data: dict = None):
        return {"success": True, "data": {"status": "ok", "message": "pong"}}

    def handler(self, data, context=None):
        return self.execute(data)
