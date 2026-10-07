from datetime import datetime

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    description: str | None = None

    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
    )

    description: str | None = None

    parent_id: int | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None

    parent_id: int | None

    is_active: bool

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True