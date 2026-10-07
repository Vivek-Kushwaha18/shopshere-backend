from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey(
            "products.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    variant_id = Column(
        Integer,
        ForeignKey(
            "product_variants.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    image_url = Column(
        String(500),
        nullable=False,
    )

    view_type = Column(
        String(50),
        nullable=True,
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    is_primary = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    product = relationship(
        "Product",
        back_populates="images",
    )

    variant = relationship(
        "ProductVariant",
        back_populates="images",
    )