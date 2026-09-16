from sqlalchemy import Column, Integer, String, ForeignKey
from app.models.base import Base


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False
    )

    image_url = Column(
        String(500),
        nullable=False
    )