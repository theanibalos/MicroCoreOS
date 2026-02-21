from core.base_plugin import BasePlugin
from domains.orders.models.order_model import OrderRequest, OrderResponse

class CreateOrderPlugin(BasePlugin):
    """
    Business logic for creating orders using cross-domain requests.
    Now emits 'orders.created' for dashboard visibility.
    """
    def __init__(self, logger, event_bus, http):
        self.logger = logger
        self.bus = event_bus
        self.http = http

    def on_boot(self):
        self.http.add_endpoint(
            path="/orders/create", 
            method="POST", 
            handler=self.execute,
            request_model=OrderRequest,
            response_model=OrderResponse,
            tags=["Orders"]
        )

    def execute(self, data: dict, context=None):
        product_id = data.get("product_id")
        quantity = data.get("quantity", 1)
        
        self.logger.info(f"OrdersPlugin: Requesting stock for Product {product_id}")

        # Request to Products domain
        stock_info = self.bus.request("products.check_stock", {"product_id": product_id})

        if not stock_info or not stock_info.get("is_available"):
            return OrderResponse(success=False, message=f"Product {product_id} out of stock.")

        self.logger.info(f"OrdersPlugin: Order approved.")
        
        # --- NEW: EMIT EVENT FOR DASHBOARD ---
        order_data = {
            "order_id": 555,
            "product_id": product_id,
            "quantity": quantity,
            "stock_snapshot": stock_info
        }
        self.bus.publish("orders.created", order_data)
        
        return OrderResponse(
            success=True,
            message="Order successful",
            order_id=555,
            stock_snapshot=stock_info
        )
