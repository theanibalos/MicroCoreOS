from pydantic import BaseModel
from typing import Optional, Dict

class OrderRequest(BaseModel):
    product_id: int
    quantity: int = 1

class OrderResponse(BaseModel):
    success: bool
    message: str
    order_id: Optional[int] = None
    stock_snapshot: Optional[Dict] = None

class StockRequest(BaseModel):
    product_id: int

class StockResponse(BaseModel):
    is_available: bool
    stock: int
