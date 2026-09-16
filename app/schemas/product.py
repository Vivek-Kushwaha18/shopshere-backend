from pydantic import BaseModel, Field


class ProductCreate(BaseModel):

    name: str = Field(
        min_length=2,
        max_length=150
    )

    description: str | None = None

    price: int = Field(
        gt=0
    )

    quantity: int = Field(
        ge=0
    )

    category: str = Field(
        min_length=2,
        max_length=100
    )

    image_url: str | None = None


class ProductUpdate(BaseModel):

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=150
    )

    description: str | None = None

    price: int | None = Field(
        default=None,
        gt=0
    )

    quantity: int | None = Field(
        default=None,
        ge=0
    )

    category: str | None = Field(
        default=None,
        min_length=2,
        max_length=100
    )

    image_url: str | None = None