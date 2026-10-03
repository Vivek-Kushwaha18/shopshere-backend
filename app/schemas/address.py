from datetime import datetime

from pydantic import BaseModel, Field


class AddressCreate(BaseModel):
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
    )

    phone: str = Field(
        ...,
        min_length=5,
        max_length=30,
    )

    address_line: str = Field(
        ...,
        min_length=5,
    )

    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    state: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    postal_code: str = Field(
        ...,
        min_length=3,
        max_length=20,
    )

    address_type: str = Field(
        default="Home",
        min_length=2,
        max_length=30,
    )

    is_default: bool = False


class AddressUpdate(BaseModel):
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
    )

    phone: str = Field(
        ...,
        min_length=5,
        max_length=30,
    )

    address_line: str = Field(
        ...,
        min_length=5,
    )

    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    state: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    postal_code: str = Field(
        ...,
        min_length=3,
        max_length=20,
    )

    address_type: str = Field(
        default="Home",
        min_length=2,
        max_length=30,
    )

    is_default: bool = False


class AddressResponse(BaseModel):
    id: int
    user_id: int
    full_name: str
    phone: str
    address_line: str
    city: str
    state: str
    postal_code: str
    address_type: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
    }