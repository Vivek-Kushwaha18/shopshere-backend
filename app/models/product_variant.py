from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProductVariant(Base):
    __tablename__ = "product_variants"

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

    sku = Column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
    )

    price = Column(
        Float,
        nullable=False,
    )

    original_price = Column(
        Float,
        nullable=True,
    )

    stock = Column(
        Integer,
        nullable=False,
        default=0,
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    product = relationship(
        "Product",
        back_populates="variants",
    )

    option_values = relationship(
        "ProductVariantValue",
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    images = relationship(
        "ProductImage",
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def option_value_ids(self) -> list[int]:
        return [
            item.option_value_id
            for item in self.option_values
        ]