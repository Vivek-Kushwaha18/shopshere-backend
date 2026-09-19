from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: float
    original_price: float | None = None
    stock: int = 0
    image: str | None = None
    category_id: int


class ProductResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    price: float
    original_price: float | None = None
    stock: int
    image: str | None = None
    rating: float
    reviews_count: int
    category_id: int

    model_config = ConfigDict(from_attributes=True)