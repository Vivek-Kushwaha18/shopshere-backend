from pydantic import BaseModel, Field


class OrderCreate(BaseModel):

    user_id: int = Field(
        gt=0
    )

    product_id: int = Field(
        gt=0
    )

    quantity: int = Field(
        gt=0
    )

    total_price: float = Field(
        gt=0
    )


class OrderUpdate(BaseModel):

    quantity: int | None = Field(
        default=None,
        gt=0
    )

    status: str | None = Field(
        default=None,
        min_length=2,
        max_length=50
    )