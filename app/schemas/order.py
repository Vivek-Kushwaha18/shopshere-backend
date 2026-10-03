from datetime import datetime

from pydantic import BaseModel, Field


# =========================================================
# CREATE ORDER
# =========================================================

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(
        ...,
        gt=0,
    )


class OrderCreate(BaseModel):
    shipping_address: str = Field(
        ...,
        min_length=5,
    )

    items: list[OrderItemCreate] = Field(
        ...,
        min_length=1,
    )


# =========================================================
# ORDER ITEM RESPONSE
# =========================================================

class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    product_id: int
    seller_id: int

    product_name: str
    product_image: str | None = None

    quantity: int
    price: float
    total: float

    model_config = {
        "from_attributes": True,
    }


# =========================================================
# ORDER RESPONSE
# =========================================================

class OrderResponse(BaseModel):
    id: int
    user_id: int
    total_amount: float
    status: str
    payment_status: str
    shipping_address: str
    created_at: datetime
    updated_at: datetime

    items: list[OrderItemResponse] = []

    model_config = {
        "from_attributes": True,
    }