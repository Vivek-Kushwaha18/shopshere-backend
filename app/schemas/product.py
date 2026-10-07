from datetime import datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


# =========================================================
# PRODUCT CREATE / UPDATE
# =========================================================

class ProductCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=255,
    )

    description: Optional[str] = None

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

    category_id: int

    image_url: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=255,
    )

    description: Optional[str] = None

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

    category_id: Optional[int] = None

    image_url: Optional[str] = None


class StockUpdate(BaseModel):
    stock: int = Field(
        ge=0,
    )


# =========================================================
# PRODUCT OPTION REQUESTS
# =========================================================

class ProductOptionValueCreate(BaseModel):
    value: str = Field(
        min_length=1,
        max_length=100,
    )

    sort_order: int = Field(
        default=0,
        ge=0,
    )


class ProductOptionGroupCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )

    sort_order: int = Field(
        default=0,
        ge=0,
    )

    values: list[
        ProductOptionValueCreate
    ] = Field(
        default_factory=list,
    )


# =========================================================
# PRODUCT VARIANT REQUEST
# =========================================================

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

    is_active: bool = True

    option_value_ids: list[int] = Field(
        default_factory=list,
    )


# =========================================================
# PRODUCT CREATE REQUEST
#
# This is the JSON structure that the frontend will send
# inside multipart/form-data.
# =========================================================

class ProductConfigurationCreate(BaseModel):
    option_groups: list[
        ProductOptionGroupCreate
    ] = Field(
        default_factory=list,
    )

    variants: list[
        ProductVariantCreate
    ] = Field(
        default_factory=list,
    )


# =========================================================
# IMAGE RESPONSE
# =========================================================

class ProductImageResponse(BaseModel):
    id: int

    image_url: str

    variant_id: Optional[int] = None

    view_type: Optional[str] = None

    sort_order: int

    is_primary: bool

    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# OPTION VALUE RESPONSE
# =========================================================

class ProductOptionValueResponse(BaseModel):
    id: int

    option_group_id: int

    value: str

    sort_order: int

    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# OPTION GROUP RESPONSE
# =========================================================

class ProductOptionGroupResponse(BaseModel):
    id: int

    product_id: int

    name: str

    sort_order: int

    values: list[
        ProductOptionValueResponse
    ] = Field(
        default_factory=list
    )

    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# VARIANT RESPONSE
# =========================================================

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

    images: list[
        ProductImageResponse
    ] = Field(
        default_factory=list
    )

    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# PRODUCT RESPONSE
# =========================================================

class ProductResponse(BaseModel):
    id: int

    seller_id: int

    category_id: int

    name: str

    slug: str

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

    option_groups: list[
        ProductOptionGroupResponse
    ] = Field(
        default_factory=list
    )

    variants: list[
        ProductVariantResponse
    ] = Field(
        default_factory=list
    )

    model_config = ConfigDict(
        from_attributes=True
    )