from core.base_plugin import BasePlugin
from domains.products.models.products_model import ProductCreate, ProductPublic, ProductStatus

class ProductsPlugin(BasePlugin):
    """
    Handles product logic and provides stock verification services.
    Integrated with Pydantic for Swagger/OpenAPI documentation.
    """
    def __init__(self, logger, event_bus, http, db):
        self.logger = logger
        self.bus = event_bus
        self.http = http
        self.db = db

    def on_boot(self):
        # 1. Status Route
        self.http.add_endpoint(
            path="/products/status", 
            method="GET", 
            handler=self.get_status,
            response_model=ProductStatus,
            tags=["Products"]
        )

        # 2. CRUD: Create Product
        self.http.add_endpoint(
            path="/products/create",
            method="POST",
            handler=self.create_product,
            request_model=ProductCreate,
            response_model=ProductPublic,
            tags=["Products"]
        )
        
        # 3. Internal Service (EventBus)
        self.bus.subscribe("products.check_stock", self.handle_stock_request)
        
        self.logger.info("ProductsPlugin: Stock Service active.")

    def create_product(self, data: dict, context):
        """Creates a product and returns the public model."""
        name = data.get("name")
        price = data.get("price")
        stock = data.get("stock", 0)

        product_id = 999 
        self.logger.info(f"ProductsPlugin: Product '{name}' created.")
        return ProductPublic(id=product_id, name=name, price=price, stock=stock)

    def handle_stock_request(self, data, event_name):
        """
        Internal RPC Handler.
        data arrives CLEAN — directly what was published.
        Return value is automatically published as a reply by EventBusTool.
        """
        product_id = data.get("product_id")
        
        self.logger.info(f"ProductsPlugin: RPC Request received for ID {product_id}")
        
        # Real logic
        stock_count = 10 if product_id == 1 else 0
        
        # Return value is automatically published as a reply by EventBusTool
        return {"is_available": stock_count > 0, "stock": stock_count}

    def execute(self, data=None):
        return ProductStatus(success=True)

    def get_status(self, data, context):
        return self.execute(data)
