from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProductOptionValueCreate(BaseModel):
    value: str = Field(min_length=1, max_length=100)
    sort_order: int = 0


class ProductOptionValueResponse(BaseModel):
    id: int
    option_group_id: int
    value: str
    sort_order: int

    model_config = ConfigDict(from_attributes=True)


class ProductOptionGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    values: list[ProductOptionValueCreate] = Field(
        default_factory=list
    )


class ProductOptionGroupResponse(BaseModel):
    id: int
    product_id: int
    name: str
    sort_order: int
    values: list[ProductOptionValueResponse] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)


class ProductVariantCreate(BaseModel):
    sku: Optional[str] = Field(
        default=None,
        max_length=100,
    )
    price: float = Field(
        ge=0,
    )
    original_price: Optional[float] = Field(
        default=None,
        ge=0,
    )
    stock: int = Field(
        default=0,
        ge=0,
    )
    option_value_ids: list[int] = Field(
        default_factory=list
    )


class ProductVariantUpdate(BaseModel):
    sku: Optional[str] = Field(
        default=None,
        max_length=100,
    )
    price: Optional[float] = Field(
        default=None,
        ge=0,
    )
    original_price: Optional[float] = Field(
        default=None,
        ge=0,
    )
    stock: Optional[int] = Field(
        default=None,
        ge=0,
    )
    is_active: Optional[bool] = None
    option_value_ids: Optional[list[int]] = None


class ProductVariantResponse(BaseModel):
    id: int
    product_id: int
    sku: Optional[str] = None
    price: float
    original_price: Optional[float] = None
    stock: int
    is_active: bool

    option_value_ids: list[int] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)