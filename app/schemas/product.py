from datetime import datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    original_price: Optional[float] = None
    stock: int = 0
    category_id: int
    image_url: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    stock: Optional[int] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None


class StockUpdate(BaseModel):
    stock: int


class ProductImageResponse(BaseModel):
    id: int
    image_url: str
    is_primary: bool

    model_config = ConfigDict(
        from_attributes=True
    )


class ProductResponse(BaseModel):
    id: int
    seller_id: int
    category_id: int

    name: str
    description: Optional[str] = None

    price: float
    original_price: Optional[float] = None

    stock: int

    image_url: Optional[str] = None

    rating: float
    reviews_count: int

    is_active: bool
    is_deleted: bool

    created_at: datetime
    updated_at: datetime

    images: list[
        ProductImageResponse
    ] = Field(
        default_factory=list
    )

    model_config = ConfigDict(
        from_attributes=True
    )