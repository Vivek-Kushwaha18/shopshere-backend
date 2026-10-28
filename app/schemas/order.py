
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OrderItemCreate(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(..., gt=0)


class OrderCreate(BaseModel):
    shipping_address: str = Field(..., min_length=5)
    items: list[OrderItemCreate] = Field(..., min_length=1)
    coupon_code: str | None = Field(default=None, max_length=50)
    payment_method: Literal["stripe", "razorpay", "cod"] = "stripe"
    idempotency_key: str | None = Field(
        default=None,
        min_length=16,
        max_length=100,
    )


class OrderVariantOptionResponse(BaseModel):
    group_name: str
    value: str


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    product_id: int
    variant_id: int | None = None
    seller_id: int
    seller_name: str | None = None
    product_name: str
    product_image: str | None = None
    variant_sku: str | None = None
    variant_options: list[OrderVariantOptionResponse] = Field(
        default_factory=list
    )
    quantity: int
    price: float
    total: float

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    user_id: int
    total_amount: float
    discount_amount: float
    coupon_code: str | None = None
    status: str
    payment_status: str
    shipping_address: str
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
