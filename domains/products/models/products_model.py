from pydantic import BaseModel
from typing import Optional

class ProductsBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProductsCreate(ProductsBase):
    pass

class ProductsPublic(ProductsBase):
    id: int
