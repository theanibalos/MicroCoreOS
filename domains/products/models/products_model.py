from typing import Optional, List
from pydantic import BaseModel, Field

# --- Product Models ---
class ProductBase(BaseModel):
    name: str = Field(..., example="Cyber Widget")
    price: float = Field(..., gt=0)
    stock: int = Field(default=0, ge=0)

class ProductCreate(ProductBase):
    """Schema for creating a new product."""
    pass

class ProductPublic(ProductBase):
    """Schema for returning product data."""
    id: int

class ProductStatus(BaseModel):
    """Simple status check response."""
    success: bool
    domain: str = "products"

# --- Request/Response Models for Services ---
class StockRequest(BaseModel):
    product_id: int

class StockResponse(BaseModel):
    is_available: bool
    stock: int
